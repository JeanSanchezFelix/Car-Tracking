from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor
from backend.app.utils.validation import escape_like


class Driver(BaseModel):
    driver_id: int | None = None
    first_name: str
    last_name: str
    license_number: str
    hired_at: datetime


class LicenseNumberTaken(Exception):
    """license_number already belongs to another driver."""


class DriverDAO:
    _DETAIL_COLUMNS = """
        driver_id, first_name, last_name, license_number, hired_at
    """

    @staticmethod
    def _filters(
        *,
        name: str | None = None,
        license_number: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if name is not None:
            # Matches "Elena", "Rivera" and "Elena Rivera".
            conditions.append("concat_ws(' ', first_name, last_name) ILIKE %s")
            values.append(f"%{escape_like(name)}%")
        if license_number is not None:
            conditions.append("license_number ILIKE %s")
            values.append(f"%{escape_like(license_number)}%")
        return conditions, values

    @staticmethod
    def _check_license(
        cur, license_number: str, exclude_driver_id: int | None = None
    ) -> None:
        """Raise LicenseNumberTaken if another driver has this license.
        Call after locking the driver table, in the same transaction as the write."""
        cur.execute(
            "SELECT 1 FROM driver "
            "WHERE license_number = %s "
            "AND (%s::bigint IS NULL OR driver_id <> %s::bigint)",
            (license_number, exclude_driver_id, exclude_driver_id),
        )
        if cur.fetchone() is not None:
            raise LicenseNumberTaken()

    def create_driver(self, driver: Driver) -> dict[str, Any]:
        """Insert a driver and return the stored row. Raises LicenseNumberTaken."""
        with cursor() as cur:
            # The supplied table has no identity or sequence for driver_id.
            cur.execute("LOCK TABLE driver IN EXCLUSIVE MODE")
            self._check_license(cur, driver.license_number)
            cur.execute(
                "SELECT COALESCE(MAX(driver_id), 0) + 1 AS driver_id FROM driver"
            )
            driver_id = cur.fetchone()["driver_id"]
            cur.execute(
                """
                INSERT INTO driver
                    (driver_id, first_name, last_name, license_number, hired_at)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING driver_id, first_name, last_name, license_number, hired_at
                """,
                (
                    driver_id,
                    driver.first_name,
                    driver.last_name,
                    driver.license_number,
                    driver.hired_at,
                ),
            )
            return dict(cur.fetchone())

    def get_drivers(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        name: str | None = None,
        license_number: str | None = None,
    ) -> dict[str, Any]:
        conditions, filter_values = self._filters(
            name=name,
            license_number=license_number,
        )
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS count FROM driver{where}", filter_values)
            count = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT driver_id, first_name, last_name, license_number, hired_at
                FROM driver
                """
                + where
                + " ORDER BY driver_id LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            )
            items = [dict(row) for row in cur.fetchall()]
        return {"items": items, "limit": limit, "offset": offset, "count": count}

    def get_driver_by_id(self, driver_id: int) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                f"SELECT {self._DETAIL_COLUMNS} FROM driver WHERE driver_id = %s",
                (driver_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_driver(self, driver_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        """Partial update. Raises LicenseNumberTaken."""
        allowed = {"first_name", "last_name", "license_number", "hired_at"}
        if not fields:
            raise ValueError("At least one driver field must be provided")
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(f"Unsupported driver fields: {', '.join(sorted(unknown))}")

        assignments: list[str] = []
        values: list[Any] = []
        for field, value in fields.items():
            assignments.append(f"{field} = %s")
            values.append(value)
        values.append(driver_id)

        with cursor() as cur:
            if "license_number" in fields:
                cur.execute("LOCK TABLE driver IN EXCLUSIVE MODE")
                self._check_license(cur, fields["license_number"], driver_id)
            cur.execute(
                f"UPDATE driver SET {', '.join(assignments)} "
                f"WHERE driver_id = %s RETURNING {self._DETAIL_COLUMNS}",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_driver(self, driver_id: int) -> bool:
        with cursor() as cur:
            cur.execute("DELETE FROM driver WHERE driver_id = %s", (driver_id,))
            return cur.rowcount == 1