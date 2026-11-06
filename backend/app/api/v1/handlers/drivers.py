from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Query

from backend.app.services.drivers import DriverService
from backend.app.utils.timeutil import parse_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    clean_text,
    reject_unknown_fields,
    require_positive_id,
)

router = APIRouter(prefix="/drivers", tags=["Drivers"])

FIELDS = ("first_name", "last_name", "license_number", "hired_at")


def _check_field(name: str, value):
    """Validate one driver field; every rejection is a 422."""
    if name == "hired_at":
        return parse_rfc3339(value, name, status_code=422)  # also rejects null / missing
    return clean_text(value, name, required=True, status_code=422)  # trimmed, non-empty


@router.post("", status_code=201)
def create_driver(payload: Dict[str, Any] = Body(...)):
    reject_unknown_fields(payload, FIELDS)
    driver = {name: _check_field(name, payload.get(name)) for name in FIELDS}
    return DriverService().create_driver(**driver)


@router.get("")
def list_drivers(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    name: Optional[str] = None,
    license_number: Optional[str] = None,
):
    name = clean_text(name, "name") or None  # blank -> no filter
    license_number = clean_text(license_number, "license_number") or None
    return DriverService().list_drivers(limit, offset, name, license_number)


@router.get("/{driver_id}")
def get_driver(driver_id: int):
    driver_id = require_positive_id(driver_id, "driver_id")
    return DriverService().get_driver(driver_id)


@router.put("/{driver_id}")
def update_driver(driver_id: int, payload: Dict[str, Any] = Body(...)):
    driver_id = require_positive_id(driver_id, "driver_id")
    reject_unknown_fields(payload, FIELDS)
    if not payload:
        raise bad_request("At least one updatable field must be supplied.")
    fields = {name: _check_field(name, payload[name]) for name in FIELDS if name in payload}
    return DriverService().update_driver(driver_id, fields)


@router.delete("/{driver_id}")
def delete_driver(driver_id: int):
    driver_id = require_positive_id(driver_id, "driver_id")
    return DriverService().delete_driver(driver_id)
