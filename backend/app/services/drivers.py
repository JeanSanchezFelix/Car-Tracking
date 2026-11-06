from typing import Optional

from psycopg2 import errors as pg_errors

from backend.app.dao.drivers import DriverDAO, LicenseNumberTaken
from backend.app.utils.timeutil import to_rfc3339
from backend.app.utils.validation import conflict, not_found


def _driver_response(row: dict) -> dict:
    return {
        "driver_id": row["driver_id"],
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "license_number": row["license_number"],
        "hired_at": to_rfc3339(row["hired_at"]),
    }


class DriverService:
    def __init__(self):
        self.dao = DriverDAO()

    # POST /api/v1/drivers
    def create_driver(self, first_name, last_name, license_number, hired_at) -> dict:
        try:
            row = self.dao.create_driver(first_name, last_name, license_number, hired_at)
        except LicenseNumberTaken:
            raise conflict("license_number already exists.")
        return _driver_response(row)

    # GET /api/v1/drivers
    def list_drivers(self, limit: int, offset: int, name: Optional[str], license_number: Optional[str]) -> dict:
        rows, total = self.dao.get_drivers(limit, offset, name, license_number)
        return {
            "items": [_driver_response(r) for r in rows],
            "limit": limit,
            "offset": offset,
            "count": total,  # matches before pagination
        }

    # GET /api/v1/drivers/{driver_id}
    def get_driver(self, driver_id: int) -> dict:
        row = self.dao.get_driver_by_id(driver_id)
        if row is None:
            raise not_found("driver_id does not exist.")
        return _driver_response(row)

    # PUT /api/v1/drivers/{driver_id}  (partial or full)
    def update_driver(self, driver_id: int, fields: dict) -> dict:
        if self.dao.get_driver_by_id(driver_id) is None:
            raise not_found("driver_id does not exist.")
        try:
            row = self.dao.update_driver(driver_id, fields)
        except LicenseNumberTaken:
            raise conflict("license_number already belongs to another driver.")
        if row is None:  # deleted between the check above and the update
            raise not_found("driver_id does not exist.")
        return _driver_response(row)

    # DELETE /api/v1/drivers/{driver_id}
    def delete_driver(self, driver_id: int) -> dict:
        if self.dao.get_driver_by_id(driver_id) is None:
            raise not_found("driver_id does not exist.")
        # No cascade deletes: assignments that use the driver must be deleted first.
        if self.dao.is_referenced(driver_id):
            raise conflict("Driver is referenced by a vehicle assignment and cannot be deleted.")
        try:
            deleted = self.dao.delete_driver(driver_id)
        except pg_errors.ForeignKeyViolation:  # an assignment was added after the check above
            raise conflict("Driver is referenced by a vehicle assignment and cannot be deleted.")
        if not deleted:
            raise not_found("driver_id does not exist.")
        return {"message": "Driver deleted successfully.", "driver_id": driver_id}
