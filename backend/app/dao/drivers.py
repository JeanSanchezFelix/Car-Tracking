from psycopg2 import sql

from backend.app.dao.connection import cursor
from backend.app.utils.validation import escape_like

# Columns a client may change with PUT. Used as a whitelist when building the UPDATE.
UPDATABLE_COLUMNS = ("first_name", "last_name", "license_number", "hired_at")

_RETURNING = sql.SQL("driver_id, first_name, last_name, license_number, hired_at")


class LicenseNumberTaken(Exception):
    """license_number already belongs to another driver."""


class DriverDAO:
    def is_referenced(self, driver_id: int) -> bool:
        """True if a vehicle assignment still points at this driver (no cascade deletes)."""
        with cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM vehicle_assignment WHERE driver_id = %s) AS referenced",
                (driver_id,),
            )
            return cur.fetchone()["referenced"]

    @staticmethod
    def _lock_and_check_license(cur, license_number: str, exclude_driver_id=None) -> None:
        """Lock the table, then raise LicenseNumberTaken if another driver has this license."""
        cur.execute("LOCK TABLE driver IN SHARE ROW EXCLUSIVE MODE")
        cur.execute(
            "SELECT 1 FROM driver "
            "WHERE license_number = %s AND (%s::bigint IS NULL OR driver_id <> %s::bigint)",
            (license_number, exclude_driver_id, exclude_driver_id),
        )
        if cur.fetchone() is not None:
            raise LicenseNumberTaken()

    def create_driver(self, first_name, last_name, license_number, hired_at):
        """Inserts with driver_id = MAX + 1. Raises LicenseNumberTaken."""
        query = sql.SQL(
            "INSERT INTO driver (driver_id, first_name, last_name, license_number, hired_at) "
            "VALUES ((SELECT COALESCE(MAX(driver_id), 0) + 1 FROM driver), %s, %s, %s, %s) "
            "RETURNING {}"
        ).format(_RETURNING)
        with cursor() as cur:
            self._lock_and_check_license(cur, license_number)
            cur.execute(query, (first_name, last_name, license_number, hired_at))
            return cur.fetchone()

    def get_driver_by_id(self, driver_id: int):
        query = sql.SQL("SELECT {} FROM driver WHERE driver_id = %s").format(_RETURNING)
        with cursor() as cur:
            cur.execute(query, (driver_id,))
            return cur.fetchone()

    def get_drivers(self, limit, offset, name=None, license_number=None):
        """Returns (rows, total_matches). Filters are optional and combine with AND.
        name is a case-insensitive partial match across first and last name, so "Elena",
        "Rivera" and "Elena Rivera" all match; license_number is a case-insensitive partial match."""
        conditions, params = [], []
        if name is not None:
            conditions.append(sql.SQL("concat_ws(' ', first_name, last_name) ILIKE %s"))
            params.append(f"%{escape_like(name)}%")
        if license_number is not None:
            conditions.append(sql.SQL("license_number ILIKE %s"))
            params.append(f"%{escape_like(license_number)}%")
        where = (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)) if conditions else sql.SQL("")

        count_query = sql.SQL("SELECT COUNT(*) AS total FROM driver{}").format(where)
        list_query = sql.SQL(
            "SELECT {} FROM driver{} ORDER BY driver_id LIMIT %s OFFSET %s"
        ).format(_RETURNING, where)
        with cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()["total"]
            cur.execute(list_query, params + [limit, offset])
            return cur.fetchall(), total

    def update_driver(self, driver_id: int, fields: dict):
        """Partial update: only the columns present in `fields` are touched.
        Returns None if the driver does not exist. Raises LicenseNumberTaken."""
        columns = [c for c in UPDATABLE_COLUMNS if c in fields]
        assignments = [sql.SQL("{} = %s").format(sql.Identifier(c)) for c in columns]
        query = sql.SQL("UPDATE driver SET {} WHERE driver_id = %s RETURNING {}").format(
            sql.SQL(", ").join(assignments), _RETURNING
        )
        with cursor() as cur:
            if "license_number" in fields:
                self._lock_and_check_license(cur, fields["license_number"], driver_id)
            cur.execute(query, [fields[c] for c in columns] + [driver_id])
            return cur.fetchone()

    def delete_driver(self, driver_id: int) -> bool:
        with cursor() as cur:
            cur.execute("DELETE FROM driver WHERE driver_id = %s RETURNING driver_id", (driver_id,))
            return cur.fetchone() is not None
