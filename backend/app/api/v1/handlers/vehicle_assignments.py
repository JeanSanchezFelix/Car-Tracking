from fastapi import APIRouter, Query
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from backend.app.dao.vehicle_assignments import VehicleAssignment, VehicleAssignmentDAO
from backend.app.utils.timeutil import parse_rfc3339, to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    not_found,
    require_later,
    require_positive_id,
)


# ---------- request bodies ----------
class VehicleAssignmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt
    driver_id: StrictInt
    assigned_from: StrictStr
    assigned_to: StrictStr | None = None


class VehicleAssignmentUpdate(BaseModel):
    """Send only the fields to change; assigned_to may be cleared with null."""

    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt | None = None
    driver_id: StrictInt | None = None
    assigned_from: StrictStr | None = None
    assigned_to: StrictStr | None = None


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
    def _check_fields(sent: dict) -> dict:
        """Validate supplied fields; only assigned_to may be null."""
        fields = {}
        for name in ("vehicle_id", "driver_id"):
            if name in sent:
                fields[name] = require_positive_id(sent[name], name)
        if "assigned_from" in sent:
            fields["assigned_from"] = parse_rfc3339(sent["assigned_from"], "assigned_from")
        if "assigned_to" in sent:
            value = sent["assigned_to"]
            fields["assigned_to"] = None if value is None else parse_rfc3339(value, "assigned_to")
        return fields

    @staticmethod
    def _parse_active(value: str | None) -> bool | None:
        if value is None or not value.strip():
            return None
        text = value.strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False
        raise bad_request("active must be true or false.")

    # ---------- endpoints ----------
    def create_assignment(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        require_later(fields["assigned_from"], fields["assigned_to"], "assigned_from", "assigned_to")
        dao = VehicleAssignmentDAO()
        try:
            row = dao.create_assignment(VehicleAssignment(**fields))
        except pg_errors.ForeignKeyViolation:  # vehicle or driver does not exist
            raise not_found("vehicle_id or driver_id does not exist.")
        return self._response(row)

    def list_assignments(
        self,
        limit: int,
        offset: int,
        vehicle_id: int | None,
        driver_id: int | None,
        active: str | None,
    ) -> dict:
        if vehicle_id is not None:
            vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        if driver_id is not None:
            driver_id = require_positive_id(driver_id, "driver_id")
        dao = VehicleAssignmentDAO()
        result = dao.get_assignments(
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
        row = dao.get_assignment_by_id(assignment_id)
        if row is None:
            raise not_found("assignment_id does not exist.")
        return self._response(row)

    def update_assignment(self, assignment_id: int, sent: dict) -> dict:
        assignment_id = require_positive_id(assignment_id, "assignment_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)

        dao = VehicleAssignmentDAO()
        current = dao.get_assignment_by_id(assignment_id)
        if current is None:
            raise not_found("assignment_id does not exist.")
        # The interval is checked on the row as it will look after the update (422 if invalid).
        assigned_from = fields.get("assigned_from", current["assigned_from"])
        assigned_to = fields["assigned_to"] if "assigned_to" in fields else current["assigned_to"]
        require_later(assigned_from, assigned_to, "assigned_from", "assigned_to")

        try:
            row = dao.update_assignment(assignment_id, fields)
        except pg_errors.ForeignKeyViolation:  # vehicle or driver does not exist
            raise not_found("vehicle_id or driver_id does not exist.")
        if row is None:  # deleted between the check above and the update
            raise not_found("assignment_id does not exist.")
        return self._response(row)

    def delete_assignment(self, assignment_id: int) -> dict:
        assignment_id = require_positive_id(assignment_id, "assignment_id")
        dao = VehicleAssignmentDAO()
        if not dao.delete_assignment(assignment_id):
            raise not_found("assignment_id does not exist.")
        return {"message": "Vehicle assignment deleted successfully.", "assignment_id": assignment_id}


# ---------- routes ----------
router = APIRouter(prefix="/vehicle-assignments", tags=["Vehicle Assignments"])


@router.post("", status_code=201)
def create_assignment(payload: VehicleAssignmentCreate):
    return VehicleAssignmentHandler().create_assignment(payload.model_dump())


@router.get("")
def list_assignments(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    vehicle_id: int | None = None,
    driver_id: int | None = None,
    active: str | None = None,  # true | false
):
    return VehicleAssignmentHandler().list_assignments(limit, offset, vehicle_id, driver_id, active)


@router.get("/{assignment_id}")
def get_assignment(assignment_id: int):
    return VehicleAssignmentHandler().get_assignment(assignment_id)


@router.put("/{assignment_id}")
def update_assignment(assignment_id: int, payload: VehicleAssignmentUpdate):
    return VehicleAssignmentHandler().update_assignment(assignment_id, payload.model_dump(exclude_unset=True))


@router.delete("/{assignment_id}")
def delete_assignment(assignment_id: int):
    return VehicleAssignmentHandler().delete_assignment(assignment_id)
