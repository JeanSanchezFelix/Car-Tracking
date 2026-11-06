from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query
from psycopg2 import errors as pg_errors

from backend.app.dao.vehicle_assignments import VehicleAssignment, VehicleAssignmentDAO
from backend.app.utils.timeutil import parse_rfc3339, to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    not_found,
    reject_unknown_fields,
    require_later,
    require_positive_id,
)

FIELDS = ("vehicle_id", "driver_id", "assigned_from", "assigned_to")


class VehicleAssignmentHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(row: dict) -> dict:
        return {
            "assignment_id": row["assignment_id"],
            "vehicle_id": row["vehicle_id"],
            "driver_id": row["driver_id"],
            "assigned_from": to_rfc3339(row["assigned_from"]),
            "assigned_to": to_rfc3339(row["assigned_to"]),
        }

    @staticmethod
    def _check_field(name: str, value):
        """Validate one field (400 if invalid). vehicle_id, driver_id and assigned_from can never be
        null; assigned_to may be null (= active assignment)."""
        if name in ("vehicle_id", "driver_id"):
            return require_positive_id(value, name)
        if name == "assigned_to" and value is None:
            return None
        return parse_rfc3339(value, name)  # also rejects null / missing assigned_from

    @staticmethod
    def _parse_active(value: Optional[str]) -> Optional[bool]:
        if value is None or not value.strip():
            return None
        text = value.strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False
        raise bad_request("active must be true or false.")

    # ---------- endpoints ----------
    def create_assignment(self, payload: dict) -> dict:
        reject_unknown_fields(payload, FIELDS)
        fields = {name: self._check_field(name, payload.get(name)) for name in FIELDS}
        require_later(fields["assigned_from"], fields["assigned_to"], "assigned_from", "assigned_to")
        dao = VehicleAssignmentDAO()
        try:
            row = dao.create(VehicleAssignment(**fields))
        except pg_errors.ForeignKeyViolation:  # vehicle or driver does not exist
            raise not_found("vehicle_id or driver_id does not exist.")
        return self._response(row)

    def list_assignments(
        self,
        limit: int,
        offset: int,
        vehicle_id: Optional[int],
        driver_id: Optional[int],
        active: Optional[str],
    ) -> dict:
        if vehicle_id is not None:
            vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        if driver_id is not None:
            driver_id = require_positive_id(driver_id, "driver_id")
        dao = VehicleAssignmentDAO()
        result = dao.list(
            limit=limit,
            offset=offset,
            vehicle_id=vehicle_id,
            driver_id=driver_id,
            active=self._parse_active(active),
        )
        result["items"] = [self._response(r) for r in result["items"]]
        return result  # count = matches before pagination

    def get_assignment(self, assignment_id: int) -> dict:
        assignment_id = require_positive_id(assignment_id, "assignment_id")
        dao = VehicleAssignmentDAO()
        row = dao.get_by_id(assignment_id)
        if row is None:
            raise not_found("assignment_id does not exist.")
        return self._response(row)

    def update_assignment(self, assignment_id: int, payload: dict) -> dict:
        assignment_id = require_positive_id(assignment_id, "assignment_id")
        reject_unknown_fields(payload, FIELDS)
        if not payload:
            raise bad_request("At least one updatable field must be supplied.")
        fields = {name: self._check_field(name, payload[name]) for name in FIELDS if name in payload}

        dao = VehicleAssignmentDAO()
        current = dao.get_by_id(assignment_id)
        if current is None:
            raise not_found("assignment_id does not exist.")
        # The interval is checked on the row as it will look after the update (422 if invalid).
        assigned_from = fields.get("assigned_from", current["assigned_from"])
        assigned_to = fields["assigned_to"] if "assigned_to" in fields else current["assigned_to"]
        require_later(assigned_from, assigned_to, "assigned_from", "assigned_to")

        try:
            row = dao.update(assignment_id, fields)
        except pg_errors.ForeignKeyViolation:  # vehicle or driver does not exist
            raise not_found("vehicle_id or driver_id does not exist.")
        if row is None:  # deleted between the check above and the update
            raise not_found("assignment_id does not exist.")
        return self._response(row)

    def delete_assignment(self, assignment_id: int) -> dict:
        assignment_id = require_positive_id(assignment_id, "assignment_id")
        dao = VehicleAssignmentDAO()
        if not dao.delete(assignment_id):
            raise not_found("assignment_id does not exist.")
        return {"message": "Vehicle assignment deleted successfully.", "assignment_id": assignment_id}


# ---------- routes ----------
router = APIRouter(prefix="/vehicle-assignments", tags=["Vehicle Assignments"])


@router.post("", status_code=201)
def create_assignment(payload: Dict[str, Any] = Body(...)):
    return VehicleAssignmentHandler().create_assignment(payload)


@router.get("")
def list_assignments(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    vehicle_id: Optional[int] = None,
    driver_id: Optional[int] = None,
    active: Optional[str] = None,  # true | false
):
    return VehicleAssignmentHandler().list_assignments(limit, offset, vehicle_id, driver_id, active)


@router.get("/{assignment_id}")
def get_assignment(assignment_id: int):
    return VehicleAssignmentHandler().get_assignment(assignment_id)


@router.put("/{assignment_id}")
def update_assignment(assignment_id: int, payload: Dict[str, Any] = Body(...)):
    return VehicleAssignmentHandler().update_assignment(assignment_id, payload)


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: int):
    return VehicleAssignmentHandler().delete_assignment(assignment_id)
