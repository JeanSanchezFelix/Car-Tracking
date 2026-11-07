from fastapi import APIRouter, Query
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, StrictStr

from backend.app.dao.drivers import Driver, DriverDAO, LicenseNumberTaken
from backend.app.utils.timeutil import parse_rfc3339, to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    clean_text,
    conflict,
    not_found,
    require_positive_id,
)


# ---------- request bodies ----------
class DriverCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    first_name: StrictStr | None
    last_name: StrictStr | None
    license_number: StrictStr | None
    hired_at: StrictStr | None


class DriverUpdate(BaseModel):
    """Send only the fields to change; the handler rejects explicit nulls."""

    model_config = ConfigDict(extra="forbid")
    first_name: StrictStr | None = None
    last_name: StrictStr | None = None
    license_number: StrictStr | None = None
    hired_at: StrictStr | None = None


class DriverHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(row: dict) -> dict:
        return {
            "driver_id": row["driver_id"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "license_number": row["license_number"],
            "hired_at": to_rfc3339(row["hired_at"]),
        }

    @staticmethod
    def _check_fields(sent: dict) -> dict:
        """Validate supplied driver fields; invalid values produce 422."""
        fields = {}
        for name in ("first_name", "last_name", "license_number"):
            if name in sent:
                fields[name] = clean_text(sent[name], name, required=True, status_code=422)
        if "hired_at" in sent:
            fields["hired_at"] = parse_rfc3339(sent["hired_at"], "hired_at", status_code=422)
        return fields

    # ---------- endpoints ----------
    def create_driver(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        dao = DriverDAO()
        try:
            row = dao.create_driver(Driver(**fields))
        except LicenseNumberTaken:
            raise conflict("license_number already exists.")
        return self._response(row)

    def list_drivers(
        self, limit: int, offset: int, name: str | None, license_number: str | None
    ) -> dict:
        name = clean_text(name, "name") or None  # blank -> no filter
        license_number = clean_text(license_number, "license_number") or None
        dao = DriverDAO()
        result = dao.get_drivers(
            limit=limit, offset=offset, name=name, license_number=license_number
        )
        result["items"] = [self._response(r) for r in result["items"]]
        return result  # count = matches before pagination

    def get_driver(self, driver_id: int) -> dict:
        driver_id = require_positive_id(driver_id, "driver_id")
        dao = DriverDAO()
        row = dao.get_driver_by_id(driver_id)
        if row is None:
            raise not_found("driver_id does not exist.")
        return self._response(row)

    def update_driver(self, driver_id: int, sent: dict) -> dict:
        driver_id = require_positive_id(driver_id, "driver_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)

        dao = DriverDAO()
        try:
            row = dao.update_driver(driver_id, fields)
        except LicenseNumberTaken:
            raise conflict("license_number already belongs to another driver.")
        if row is None:
            raise not_found("driver_id does not exist.")
        return self._response(row)

    def delete_driver(self, driver_id: int) -> dict:
        driver_id = require_positive_id(driver_id, "driver_id")
        dao = DriverDAO()
        try:
            deleted = dao.delete_driver(driver_id)
        except pg_errors.ForeignKeyViolation:  # no cascade: a vehicle assignment still uses it
            raise conflict("Driver is referenced by a vehicle assignment and cannot be deleted.")
        if not deleted:
            raise not_found("driver_id does not exist.")
        return {"message": "Driver deleted successfully.", "driver_id": driver_id}


# ---------- routes ----------
router = APIRouter(prefix="/drivers", tags=["Drivers"])


@router.post("", status_code=201)
def create_driver(payload: DriverCreate):
    return DriverHandler().create_driver(payload.model_dump())


@router.get("")
def list_drivers(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    name: str | None = None,
    license_number: str | None = None,
):
    return DriverHandler().list_drivers(limit, offset, name, license_number)


@router.get("/{driver_id}")
def get_driver(driver_id: int):
    return DriverHandler().get_driver(driver_id)


@router.put("/{driver_id}")
def update_driver(driver_id: int, payload: DriverUpdate):
    return DriverHandler().update_driver(driver_id, payload.model_dump(exclude_unset=True))


@router.delete("/{driver_id}")
def delete_driver(driver_id: int):
    return DriverHandler().delete_driver(driver_id)
