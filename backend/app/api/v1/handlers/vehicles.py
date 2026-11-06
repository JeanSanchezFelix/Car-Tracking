from fastapi import APIRouter, Query, Response
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from backend.app.dao.vehicles import PlateNumberTaken, Vehicle, VehicleDAO
from backend.app.utils.timeutil import to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    clean_text,
    conflict,
    not_found,
    require_positive_id,
)


# ---------- request bodies: a wrong shape (bad JSON, wrong types, unknown fields) is a 400 ----------
class VehicleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_type_id: StrictInt
    vehicle_status_id: StrictInt
    plate_number: StrictStr
    make: StrictStr | None = None
    model: StrictStr | None = None
    year: StrictInt | None = None


class VehicleUpdate(BaseModel):
    """Every field is optional: send only what you want to change."""

    model_config = ConfigDict(extra="forbid")
    vehicle_type_id: StrictInt | None = None
    vehicle_status_id: StrictInt | None = None
    plate_number: StrictStr | None = None
    make: StrictStr | None = None
    model: StrictStr | None = None
    year: StrictInt | None = None


class VehicleHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(row: dict) -> dict:
        return {
            "vehicle_id": row["vehicle_id"],
            "vehicle_type_id": row["vehicle_type_id"],
            "vehicle_status_id": row["vehicle_status_id"],
            "plate_number": row["plate_number"],
            "make": row["make"],
            "model": row["model"],
            "year": row["year"],
            "created_at": to_rfc3339(row["created_at"]),
        }

    @staticmethod
    def _check_fields(sent: dict) -> dict:
        """Validate the vehicle fields present in `sent` (create sends all of them, update a subset).
        Every rejection is a 400."""
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

    @staticmethod
    def _status_filter(status: str | None) -> tuple:
        """The status filter may be a vehicle_status_id ("1") or a status name ("active").
        Returns (status_id, status_name); both None means no filter."""
        text = clean_text(status, "status")
        if not text:
            return None, None
        if text.isascii() and text.isdigit():
            return require_positive_id(int(text), "status"), None
        return None, text

    # ---------- endpoints ----------
    def create_vehicle(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        dao = VehicleDAO()
        try:
            row = dao.create_vehicle(Vehicle(**fields))
        except PlateNumberTaken:
            raise conflict("plate_number already exists.")
        except pg_errors.ForeignKeyViolation:  # type or status does not exist
            raise not_found("vehicle_type_id or vehicle_status_id does not exist.")
        return self._response(row)

    def list_vehicles(
        self, limit: int, offset: int, status: str | None, plate_number: str | None
    ) -> dict:
        status_id, status_name = self._status_filter(status)
        plate = clean_text(plate_number, "plate_number") or None  # blank -> no filter
        dao = VehicleDAO()
        result = dao.get_vehicles(
            limit=limit,
            offset=offset,
            plate_number=plate,
            status_id=status_id,
            status_name=status_name,
        )
        result["items"] = [self._response(r) for r in result["items"]]
        return result  # count = matches before pagination

    def get_vehicle(self, vehicle_id: int) -> dict:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        dao = VehicleDAO()
        row = dao.get_vehicle_by_id(vehicle_id)
        if row is None:
            raise not_found("vehicle_id does not exist.")
        return self._response(row)

    def update_vehicle(self, vehicle_id: int, sent: dict) -> dict:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)

        dao = VehicleDAO()
        try:
            row = dao.update_vehicle(vehicle_id, fields)
        except PlateNumberTaken:
            raise conflict("plate_number already belongs to another vehicle.")
        except pg_errors.ForeignKeyViolation:  # type or status does not exist
            raise not_found("vehicle_type_id or vehicle_status_id does not exist.")
        if row is None:
            raise not_found("vehicle_id does not exist.")
        return self._response(row)

    def delete_vehicle(self, vehicle_id: int) -> dict:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        dao = VehicleDAO()
        try:
            deleted = dao.delete_vehicle(vehicle_id)
        except pg_errors.ForeignKeyViolation:  # no cascade: pings, trips or assignments still use it
            raise conflict(
                "Vehicle is referenced by location pings, trips or assignments and cannot be deleted."
            )
        if not deleted:
            raise not_found("vehicle_id does not exist.")
        return {"message": "Vehicle deleted successfully.", "vehicle_id": vehicle_id}

    def get_vehicle_current_location(self, vehicle_id: int) -> dict | None:
        """Returns None when the vehicle exists but has no pings (the route turns that into 204)."""
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        dao = VehicleDAO()
        row = dao.get_vehicle_current_location(vehicle_id)
        if row is None:
            raise not_found("vehicle_id does not exist.")
        if row["ping_id"] is None:
            return None
        return {
            "vehicle_id": row["vehicle_id"],
            "plate_number": row["plate_number"],
            "status": row["status"],
            "vehicle_kind": row["vehicle_kind"],
            "fuel_type": row["fuel_type"],
            "emissions_rating": row["emissions_rating"],
            "last_ts": to_rfc3339(row["last_ts"]),
            "last_geom": row["last_geom"],
            "speed_kph": row["speed_kph"],
            "heading_deg": row["heading_deg"],
        }


# ---------- routes ----------
router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.post("", status_code=201)
def create_vehicle(payload: VehicleCreate):
    return VehicleHandler().create_vehicle(payload.model_dump())


@router.get("")
def list_vehicles(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    status: str | None = None,
    plate_number: str | None = None,
):
    return VehicleHandler().list_vehicles(limit, offset, status, plate_number)


@router.get("/{vehicle_id}/current-location")
def get_vehicle_current_location(vehicle_id: int):
    location = VehicleHandler().get_vehicle_current_location(vehicle_id)
    if location is None:  # the vehicle exists but has no pings yet
        return Response(status_code=204)
    return location


@router.get("/{vehicle_id}")
def get_vehicle(vehicle_id: int):
    return VehicleHandler().get_vehicle(vehicle_id)


@router.put("/{vehicle_id}")
def update_vehicle(vehicle_id: int, payload: VehicleUpdate):
    return VehicleHandler().update_vehicle(vehicle_id, payload.model_dump(exclude_unset=True))


@router.delete("/{vehicle_id}")
def delete_vehicle(vehicle_id: int):
    return VehicleHandler().delete_vehicle(vehicle_id)