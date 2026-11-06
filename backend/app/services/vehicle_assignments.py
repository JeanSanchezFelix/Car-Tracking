from typing import Optional

from psycopg2 import errors as pg_errors

from backend.app.dao.vehicle_assignments import VehicleAssignmentDAO
from backend.app.utils.timeutil import to_rfc3339
from backend.app.utils.validation import not_found, require_later


def _assignment_response(row: dict) -> dict:
    return {
        "assignment_id": row["assignment_id"],
        "vehicle_id": row["vehicle_id"],
        "driver_id": row["driver_id"],
        "assigned_from": to_rfc3339(row["assigned_from"]),
        "assigned_to": to_rfc3339(row["assigned_to"]),
    }


class VehicleAssignmentService:
    def __init__(self):
        self.dao = VehicleAssignmentDAO()

    def _require_references(self, vehicle_id=None, driver_id=None) -> None:
        if vehicle_id is not None and not self.dao.vehicle_exists(vehicle_id):
            raise not_found("vehicle_id does not exist.")
        if driver_id is not None and not self.dao.driver_exists(driver_id):
            raise not_found("driver_id does not exist.")

    # POST /api/v1/vehicle-assignments
    def create_assignment(self, vehicle_id, driver_id, assigned_from, assigned_to) -> dict:
        self._require_references(vehicle_id, driver_id)
        try:
            row = self.dao.create_assignment(vehicle_id, driver_id, assigned_from, assigned_to)
        except pg_errors.ForeignKeyViolation:  # vehicle/driver removed after the check above
            raise not_found("vehicle_id or driver_id does not exist.")
        return _assignment_response(row)

    # GET /api/v1/vehicle-assignments
    def list_assignments(
        self,
        limit: int,
        offset: int,
        vehicle_id: Optional[int],
        driver_id: Optional[int],
        active: Optional[bool],
    ) -> dict:
        rows, total = self.dao.get_assignments(limit, offset, vehicle_id, driver_id, active)
        return {
            "items": [_assignment_response(r) for r in rows],
            "limit": limit,
            "offset": offset,
            "count": total,  # matches before pagination
        }

    # GET /api/v1/vehicle-assignments/{assignment_id}
    def get_assignment(self, assignment_id: int) -> dict:
        row = self.dao.get_assignment_by_id(assignment_id)
        if row is None:
            raise not_found("assignment_id does not exist.")
        return _assignment_response(row)

    # PUT /api/v1/vehicle-assignments/{assignment_id}  (partial or full)
    def update_assignment(self, assignment_id: int, fields: dict) -> dict:
        current = self.dao.get_assignment_by_id(assignment_id)
        if current is None:
            raise not_found("assignment_id does not exist.")
        # The interval is checked on the row as it will look after the update (422 if invalid).
        assigned_from = fields.get("assigned_from", current["assigned_from"])
        assigned_to = fields["assigned_to"] if "assigned_to" in fields else current["assigned_to"]
        require_later(assigned_from, assigned_to, "assigned_from", "assigned_to")
        self._require_references(fields.get("vehicle_id"), fields.get("driver_id"))

        try:
            row = self.dao.update_assignment(assignment_id, fields)
        except pg_errors.ForeignKeyViolation:
            raise not_found("vehicle_id or driver_id does not exist.")
        if row is None:  # deleted between the check above and the update
            raise not_found("assignment_id does not exist.")
        return _assignment_response(row)

    # DELETE /api/v1/vehicle-assignments/{assignment_id}
    def delete_assignment(self, assignment_id: int) -> dict:
        if not self.dao.delete_assignment(assignment_id):
            raise not_found("assignment_id does not exist.")
        return {"message": "Vehicle assignment deleted successfully.", "assignment_id": assignment_id}
