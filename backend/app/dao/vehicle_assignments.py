from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor

class VehicleAssignment(BaseModel):
    assignment_id: int | None = None
    vehicle_id: int
    driver_id: int
    assigned_from: datetime
    assigned_to: datetime | None = None


class VehicleAssignmentDAO:
    _DETAIL_COLUMNS = """
        assignment_id, vehicle_id, driver_id, assigned_from, assigned_to
    """

    @staticmethod
    def _filters(
        *,
        vehicle_id: int | None = None,
        driver_id: int | None = None,
        active: bool | None = None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if vehicle_id is not None:
            conditions.append("vehicle_id = %s")
            values.append(vehicle_id)
        if driver_id is not None:
            conditions.append("driver_id = %s")
            values.append(driver_id)
        if active is True:
            conditions.append("assigned_to IS NULL")
        elif active is False:
            conditions.append("assigned_to IS NOT NULL")
        return conditions, values

    # ---------- CRUD ----------
    def create_assignment(self, assignment: VehicleAssignment) -> dict[str, Any]:
        """Insert an assignment and return the stored row."""
        with cursor() as cur:
            # The supplied table has no identity or sequence for assignment_id.
            cur.execute("LOCK TABLE vehicle_assignment IN EXCLUSIVE MODE")
            cur.execute(
                "SELECT COALESCE(MAX(assignment_id), 0) + 1 AS assignment_id "
                "FROM vehicle_assignment"
            )
            assignment_id = cur.fetchone()["assignment_id"]
            cur.execute(
                """
                INSERT INTO vehicle_assignment
                    (assignment_id, vehicle_id, driver_id, assigned_from, assigned_to)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING assignment_id, vehicle_id, driver_id,
                          assigned_from, assigned_to
                """,
                (
                    assignment_id,
                    assignment.vehicle_id,
                    assignment.driver_id,
                    assignment.assigned_from,
                    assignment.assigned_to,
                ),
            )
            return dict(cur.fetchone())

    def get_assignments(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        vehicle_id: int | None = None,
        driver_id: int | None = None,
        active: bool | None = None,
    ) -> dict[str, Any]:
        """active=True -> assigned_to IS NULL, active=False -> assigned_to IS NOT NULL."""
        conditions, filter_values = self._filters(
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            active=active,
        )
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS count FROM vehicle_assignment{where}",
                filter_values,
            )
            count = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT assignment_id, vehicle_id, driver_id, assigned_from, assigned_to
                FROM vehicle_assignment
                """
                + where
                + " ORDER BY assignment_id LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            )
            items = [dict(row) for row in cur.fetchall()]
        return {"items": items, "limit": limit, "offset": offset, "count": count}

    def get_assignment_by_id(self, assignment_id: int) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                f"SELECT {self._DETAIL_COLUMNS} FROM vehicle_assignment "
                "WHERE assignment_id = %s",
                (assignment_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_assignment(
        self, assignment_id: int, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Partial update (assigned_to may be set to None to re-open an assignment)."""
        allowed = {"vehicle_id", "driver_id", "assigned_from", "assigned_to"}
        if not fields:
            raise ValueError("At least one vehicle-assignment field must be provided")
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(
                f"Unsupported vehicle-assignment fields: {', '.join(sorted(unknown))}"
            )

        assignments: list[str] = []
        values: list[Any] = []
        for field, value in fields.items():
            assignments.append(f"{field} = %s")
            values.append(value)
        values.append(assignment_id)

        with cursor() as cur:
            cur.execute(
                f"UPDATE vehicle_assignment SET {', '.join(assignments)} "
                f"WHERE assignment_id = %s RETURNING {self._DETAIL_COLUMNS}",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_assignment(self, assignment_id: int) -> bool:
        with cursor() as cur:
            cur.execute(
                "DELETE FROM vehicle_assignment WHERE assignment_id = %s",
                (assignment_id,),
            )
            return cur.rowcount == 1