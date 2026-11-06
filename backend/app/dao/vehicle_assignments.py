from psycopg2 import sql

from backend.app.dao.connection import cursor

# Columns a client may change with PUT. Used as a whitelist when building the UPDATE.
UPDATABLE_COLUMNS = ("vehicle_id", "driver_id", "assigned_from", "assigned_to")

_RETURNING = sql.SQL("assignment_id, vehicle_id, driver_id, assigned_from, assigned_to")


class VehicleAssignmentDAO:
    # ---------- lookups used by the service's business rules ----------
    def vehicle_exists(self, vehicle_id: int) -> bool:
        with cursor() as cur:
            cur.execute("SELECT 1 FROM vehicle WHERE vehicle_id = %s", (vehicle_id,))
            return cur.fetchone() is not None

    def driver_exists(self, driver_id: int) -> bool:
        with cursor() as cur:
            cur.execute("SELECT 1 FROM driver WHERE driver_id = %s", (driver_id,))
            return cur.fetchone() is not None

    # ---------- CRUD ----------
    def create_assignment(self, vehicle_id, driver_id, assigned_from, assigned_to):
        """Inserts with assignment_id = MAX + 1."""
        query = sql.SQL(
            "INSERT INTO vehicle_assignment (assignment_id, vehicle_id, driver_id, assigned_from, assigned_to) "
            "VALUES ((SELECT COALESCE(MAX(assignment_id), 0) + 1 FROM vehicle_assignment), %s, %s, %s, %s) "
            "RETURNING {}"
        ).format(_RETURNING)
        with cursor() as cur:
            cur.execute("LOCK TABLE vehicle_assignment IN SHARE ROW EXCLUSIVE MODE")
            cur.execute(query, (vehicle_id, driver_id, assigned_from, assigned_to))
            return cur.fetchone()

    def get_assignment_by_id(self, assignment_id: int):
        query = sql.SQL("SELECT {} FROM vehicle_assignment WHERE assignment_id = %s").format(
            _RETURNING
        )
        with cursor() as cur:
            cur.execute(query, (assignment_id,))
            return cur.fetchone()

    def get_assignments(self, limit, offset, vehicle_id=None, driver_id=None, active=None):
        """Returns (rows, total_matches). Filters are optional and combine with AND.
        active=True -> assigned_to IS NULL, active=False -> assigned_to IS NOT NULL."""
        conditions, params = [], []
        if vehicle_id is not None:
            conditions.append(sql.SQL("vehicle_id = %s"))
            params.append(vehicle_id)
        if driver_id is not None:
            conditions.append(sql.SQL("driver_id = %s"))
            params.append(driver_id)
        if active is True:
            conditions.append(sql.SQL("assigned_to IS NULL"))
        elif active is False:
            conditions.append(sql.SQL("assigned_to IS NOT NULL"))
        where = (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)) if conditions else sql.SQL("")

        count_query = sql.SQL("SELECT COUNT(*) AS total FROM vehicle_assignment{}").format(where)
        list_query = sql.SQL(
            "SELECT {} FROM vehicle_assignment{} ORDER BY assignment_id LIMIT %s OFFSET %s"
        ).format(_RETURNING, where)
        with cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()["total"]
            cur.execute(list_query, params + [limit, offset])
            return cur.fetchall(), total

    def update_assignment(self, assignment_id: int, fields: dict):
        """Partial update: only the columns present in `fields` are touched
        (assigned_to may be set to None to re-open an assignment)."""
        columns = [c for c in UPDATABLE_COLUMNS if c in fields]
        assignments = [sql.SQL("{} = %s").format(sql.Identifier(c)) for c in columns]
        query = sql.SQL(
            "UPDATE vehicle_assignment SET {} WHERE assignment_id = %s RETURNING {}"
        ).format(sql.SQL(", ").join(assignments), _RETURNING)
        with cursor() as cur:
            cur.execute(query, [fields[c] for c in columns] + [assignment_id])
            return cur.fetchone()

    def delete_assignment(self, assignment_id: int) -> bool:
        with cursor() as cur:
            cur.execute(
                "DELETE FROM vehicle_assignment WHERE assignment_id = %s RETURNING assignment_id",
                (assignment_id,),
            )
            return cur.fetchone() is not None
