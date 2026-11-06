from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor
from backend.app.utils.validation import escape_like


class Vehicle(BaseModel):
    vehicle_id: int | None = None
    vehicle_type_id: int
    vehicle_status_id: int
    plate_number: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    created_at: datetime | None = None


class PlateNumberTaken(Exception):
    """plate_number already belongs to another vehicle."""


class VehicleDAO:
    _DETAIL_COLUMNS = """
        vehicle_id, vehicle_type_id, vehicle_status_id, plate_number,
        make, model, year, created_at
    """

    @staticmethod
    def _filters(
        *,
        plate_number: str | None = None,
        status_id: int | None = None,
        status_name: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if plate_number is not None:
            conditions.append("plate_number ILIKE %s")
            values.append(f"%{escape_like(plate_number)}%")
        if status_id is not None:
            conditions.append("vehicle_status_id = %s")
            values.append(status_id)
        elif status_name is not None:
            conditions.append(
                "vehicle_status_id IN (SELECT vehicle_status_id FROM vehicle_status "
                "WHERE LOWER(name) = LOWER(%s))"
            )
            values.append(status_name)
        return conditions, values

    @staticmethod
    def _check_plate(
        cur, plate_number: str, exclude_vehicle_id: int | None = None
    ) -> None:
        """Raise PlateNumberTaken if another vehicle has this plate.
        Call after locking the vehicle table, in the same transaction as the write."""
        cur.execute(
            "SELECT 1 FROM vehicle "
            "WHERE plate_number = %s "
            "AND (%s::bigint IS NULL OR vehicle_id <> %s::bigint)",
            (plate_number, exclude_vehicle_id, exclude_vehicle_id),
        )
        if cur.fetchone() is not None:
            raise PlateNumberTaken()

    # ---------- CRUD ----------
    def create_vehicle(self, vehicle: Vehicle) -> dict[str, Any]:
        """Insert a vehicle and return the stored row. Raises PlateNumberTaken."""
        with cursor() as cur:
            # The supplied table has no identity or sequence for vehicle_id.
            cur.execute("LOCK TABLE vehicle IN EXCLUSIVE MODE")
            self._check_plate(cur, vehicle.plate_number)
            cur.execute(
                "SELECT COALESCE(MAX(vehicle_id), 0) + 1 AS vehicle_id FROM vehicle"
            )
            vehicle_id = cur.fetchone()["vehicle_id"]
            cur.execute(
                """
                INSERT INTO vehicle
                    (vehicle_id, vehicle_type_id, vehicle_status_id, plate_number,
                     make, model, year, created_at)
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    date_trunc('second', now() AT TIME ZONE 'UTC')
                )
                RETURNING vehicle_id, vehicle_type_id, vehicle_status_id, plate_number,
                          make, model, year, created_at
                """,
                (
                    vehicle_id,
                    vehicle.vehicle_type_id,
                    vehicle.vehicle_status_id,
                    vehicle.plate_number,
                    vehicle.make,
                    vehicle.model,
                    vehicle.year,
                ),
            )
            return dict(cur.fetchone())

    def get_vehicles(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        plate_number: str | None = None,
        status_id: int | None = None,
        status_name: str | None = None,
    ) -> dict[str, Any]:
        conditions, filter_values = self._filters(
            plate_number=plate_number,
            status_id=status_id,
            status_name=status_name,
        )
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS count FROM vehicle{where}", filter_values)
            count = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT vehicle_id, vehicle_type_id, vehicle_status_id, plate_number,
                       make, model, year, created_at
                FROM vehicle
                """
                + where
                + " ORDER BY vehicle_id LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            )
            items = [dict(row) for row in cur.fetchall()]
        return {"items": items, "limit": limit, "offset": offset, "count": count}

    def get_vehicle_by_id(self, vehicle_id: int) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                f"SELECT {self._DETAIL_COLUMNS} FROM vehicle WHERE vehicle_id = %s",
                (vehicle_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_vehicle(self, vehicle_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Partial update. Raises PlateNumberTaken."""
        allowed = {
            "vehicle_type_id",
            "vehicle_status_id",
            "plate_number",
            "make",
            "model",
            "year",
        }
        if not fields:
            raise ValueError("At least one vehicle field must be provided")
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(f"Unsupported vehicle fields: {', '.join(sorted(unknown))}")

        assignments: list[str] = []
        values: list[Any] = []
        for field, value in fields.items():
            assignments.append(f"{field} = %s")
            values.append(value)
        values.append(vehicle_id)

        with cursor() as cur:
            if "plate_number" in fields:
                cur.execute("LOCK TABLE vehicle IN EXCLUSIVE MODE")
                self._check_plate(cur, fields["plate_number"], vehicle_id)
            cur.execute(
                f"UPDATE vehicle SET {', '.join(assignments)} "
                f"WHERE vehicle_id = %s RETURNING {self._DETAIL_COLUMNS}",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_vehicle(self, vehicle_id: int) -> bool:
        with cursor() as cur:
            cur.execute("DELETE FROM vehicle WHERE vehicle_id = %s", (vehicle_id,))
            return cur.rowcount == 1

    # ---------- current location ----------
    def get_vehicle_current_location(self, vehicle_id: int) -> dict[str, Any] | None:
        """One row for the vehicle with its most recent ping (ping columns are NULL if none)."""
        with cursor() as cur:
            cur.execute(
                """
                SELECT v.vehicle_id, v.plate_number, vs.name AS status,
                       vk.name AS vehicle_kind, ft.name AS fuel_type,
                       vt.emissions_rating, lp.ping_id, lp.ts AS last_ts,
                       ST_AsGeoJSON(lp.geom)::json AS last_geom,
                       lp.speed_kph, lp.heading_deg
                FROM vehicle v
                LEFT JOIN vehicle_status vs ON vs.vehicle_status_id = v.vehicle_status_id
                LEFT JOIN vehicle_type vt ON vt.vehicle_type_id = v.vehicle_type_id
                LEFT JOIN vehicle_kind vk ON vk.vehicle_kind_id = vt.vehicle_kind_id
                LEFT JOIN fuel_type ft ON ft.fuel_type_id = vt.fuel_type_id
                LEFT JOIN LATERAL (
                    SELECT ping_id, ts, geom, speed_kph, heading_deg
                    FROM location_ping
                    WHERE vehicle_id = v.vehicle_id
                    ORDER BY ts DESC NULLS LAST, ping_id DESC
                    LIMIT 1
                ) lp ON TRUE
                WHERE v.vehicle_id = %s
                """,
                (vehicle_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None