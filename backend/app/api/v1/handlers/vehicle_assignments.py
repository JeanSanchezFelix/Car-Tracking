from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query

from backend.app.services.vehicle_assignments import VehicleAssignmentService
from backend.app.utils.timeutil import parse_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    reject_unknown_fields,
    require_later,
    require_positive_id,
)

router = APIRouter(prefix="/vehicle-assignments", tags=["Vehicle Assignments"])

FIELDS = ("vehicle_id", "driver_id", "assigned_from", "assigned_to")


def _check_field(name: str, value):
    """Validate one field (400 if invalid). vehicle_id, driver_id and assigned_from can never be
    null; assigned_to may be null (= active assignment)."""
    if name in ("vehicle_id", "driver_id"):
        return require_positive_id(value, name)
    if name == "assigned_to" and value is None:
        return None
    return parse_rfc3339(value, name)  # also rejects null / missing assigned_from


def _parse_active(value: Optional[str]) -> Optional[bool]:
    if value is None or not value.strip():
        return None
    text = value.strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise bad_request("active must be true or false.")


@router.post("", status_code=201)
def create_assignment(payload: Dict[str, Any] = Body(...)):
    reject_unknown_fields(payload, FIELDS)
    assignment = {name: _check_field(name, payload.get(name)) for name in FIELDS}
    require_later(assignment["assigned_from"], assignment["assigned_to"], "assigned_from", "assigned_to")
    return VehicleAssignmentService().create_assignment(**assignment)


@router.get("")
def list_assignments(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    vehicle_id: Optional[int] = None,
    driver_id: Optional[int] = None,
    active: Optional[str] = None,  # true | false
):
    if vehicle_id is not None:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    if driver_id is not None:
        driver_id = require_positive_id(driver_id, "driver_id")
    return VehicleAssignmentService().list_assignments(
        limit, offset, vehicle_id, driver_id, _parse_active(active)
    )


@router.get("/{assignment_id}")
def get_assignment(assignment_id: int):
    assignment_id = require_positive_id(assignment_id, "assignment_id")
    return VehicleAssignmentService().get_assignment(assignment_id)


@router.put("/{assignment_id}")
def update_assignment(assignment_id: int, payload: Dict[str, Any] = Body(...)):
    assignment_id = require_positive_id(assignment_id, "assignment_id")
    reject_unknown_fields(payload, FIELDS)
    if not payload:
        raise bad_request("At least one updatable field must be supplied.")
    fields = {name: _check_field(name, payload[name]) for name in FIELDS if name in payload}
    # The resulting interval depends on the stored row, so the service checks it (422).
    return VehicleAssignmentService().update_assignment(assignment_id, fields)


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: int):
    assignment_id = require_positive_id(assignment_id, "assignment_id")
    return VehicleAssignmentService().delete_assignment(assignment_id)
