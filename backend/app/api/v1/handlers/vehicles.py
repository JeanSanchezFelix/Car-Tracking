from typing import Optional

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from backend.app.services.vehicles import VehicleService
from backend.app.utils.validation import MAX_BIGINT, bad_request, clean_text, require_positive_id

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


# ---------- request bodies: a wrong shape (bad JSON, wrong types, unknown fields) is a 400 ----------
class VehicleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_type_id: StrictInt
    vehicle_status_id: StrictInt
    plate_number: StrictStr
    make: Optional[StrictStr] = None
    model: Optional[StrictStr] = None
    year: Optional[StrictInt] = None


class VehicleUpdate(BaseModel):
    """Every field is optional: send only what you want to change."""

    model_config = ConfigDict(extra="forbid")
    vehicle_type_id: Optional[StrictInt] = None
    vehicle_status_id: Optional[StrictInt] = None
    plate_number: Optional[StrictStr] = None
    make: Optional[StrictStr] = None
    model: Optional[StrictStr] = None
    year: Optional[StrictInt] = None


# ---------- request validation (every rejection is a 400) ----------
def _check_fields(sent: dict) -> dict:
    """Validate the vehicle fields present in `sent` (create sends all of them, update a subset)."""
    fields = {}
    for column in ("vehicle_type_id", "vehicle_status_id"):
        if column in sent:
            fields[column] = require_positive_id(sent[column], column)
    if "plate_number" in sent:
        fields["plate_number"] = clean_text(sent["plate_number"], "plate_number", required=True)
    for column in ("make", "model"):  # optional text, trimmed; null clears it on update
        if column in sent:
            fields[column] = clean_text(sent[column], column)
    if "year" in sent:
        year = sent["year"]
        if year is not None and not 1950 <= year <= 2100:
            raise bad_request("year must be between 1950 and 2100.")
        fields["year"] = year
    return fields


def _status_filter(status: Optional[str]) -> tuple:
    """The status filter may be a vehicle_status_id ("1") or a status name ("active").
    Returns (status_id, status_name); both None means no filter."""
    text = clean_text(status, "status")
    if not text:
        return None, None
    if text.isascii() and text.isdigit():
        return require_positive_id(int(text), "status"), None
    return None, text


# ---------- endpoints ----------
@router.post("", status_code=201)
def create_vehicle(payload: VehicleCreate):
    fields = _check_fields(payload.model_dump())
    return VehicleService().create_vehicle(**fields)


@router.get("")
def list_vehicles(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    status: Optional[str] = None,
    plate_number: Optional[str] = None,
):
    status_id, status_name = _status_filter(status)
    plate = clean_text(plate_number, "plate_number") or None  # blank -> no filter
    return VehicleService().list_vehicles(limit, offset, plate, status_id, status_name)


@router.get("/{vehicle_id}/current-location")
def get_current_location(vehicle_id: int):
    vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    location = VehicleService().get_current_location(vehicle_id)
    if location is None:  # the vehicle exists but has no pings yet
        return Response(status_code=204)
    return location


@router.get("/{vehicle_id}")
def get_vehicle(vehicle_id: int):
    vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    return VehicleService().get_vehicle(vehicle_id)


@router.put("/{vehicle_id}")
def update_vehicle(vehicle_id: int, payload: VehicleUpdate):
    vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    sent = payload.model_dump(exclude_unset=True)
    if not sent:
        raise bad_request("At least one updatable field must be supplied.")
    return VehicleService().update_vehicle(vehicle_id, _check_fields(sent))


@router.delete("/{vehicle_id}")
def delete_vehicle(vehicle_id: int):
    vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    return VehicleService().delete_vehicle(vehicle_id)
