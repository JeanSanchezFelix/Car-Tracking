import json
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr

from backend.app.dao.parking_areas import ParkingArea, ParkingAreaDAO
from backend.app.utils.geo import validate_geometry
from backend.app.utils.timeutil import to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    clean_text,
    not_found,
    parse_bbox,
    require_non_negative_int,
    require_positive_id,
)


# ---------- request bodies ----------
class ParkingAreaCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr
    capacity: StrictInt | None = None
    geom: Any


class ParkingAreaUpdate(BaseModel):
    """Send only the fields to change."""

    model_config = ConfigDict(extra="forbid")
    name: StrictStr | None = None
    capacity: StrictInt | None = None
    geom: Any = None


class ParkingAreaHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(row: dict, *, include_geom: bool = True) -> dict:
        result = {
            "parking_area_id": row["parking_area_id"],
            "name": row["name"],
            "capacity": row["capacity"],
            "created_at": to_rfc3339(row["created_at"]),
        }
        if include_geom:
            result["geom"] = row["geom"]
        return result

    @staticmethod
    def _check_fields(sent: dict) -> dict:
        fields = {}
        if "name" in sent:
            fields["name"] = clean_text(sent["name"], "name", required=True)
        if "capacity" in sent:
            value = sent["capacity"]
            fields["capacity"] = None if value is None else require_non_negative_int(value, "capacity")
        if "geom" in sent:
            fields["geom"] = json.loads(validate_geometry(sent["geom"], "Polygon"))
        return fields

    # ---------- endpoints ----------
    def create_parking_area(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        dao = ParkingAreaDAO()
        if not dao.is_valid_geometry(fields["geom"]):
            raise bad_request("geom must be a valid Polygon for PostGIS storage.")
        return self._response(dao.create_parking_area(ParkingArea(**fields)))

    def list_parking_areas(self, limit: int, offset: int, name: str | None, bbox: str | None) -> dict:
        name = clean_text(name, "name") or None
        box = parse_bbox(bbox) if bbox is not None else None
        dao = ParkingAreaDAO()
        result = dao.get_parking_areas(limit=limit, offset=offset, name=name, bbox=box)
        result["items"] = [self._response(row, include_geom=False) for row in result["items"]]
        return result

    def get_parking_area(self, parking_area_id: int) -> dict:
        parking_area_id = require_positive_id(parking_area_id, "parking_area_id")
        dao = ParkingAreaDAO()
        row = dao.get_parking_area_by_id(parking_area_id)
        if row is None:
            raise not_found("parking_area_id does not exist.")
        return self._response(row)

    def update_parking_area(self, parking_area_id: int, sent: dict) -> dict:
        parking_area_id = require_positive_id(parking_area_id, "parking_area_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)
        dao = ParkingAreaDAO()
        if "geom" in fields and not dao.is_valid_geometry(fields["geom"]):
            raise bad_request("geom must be a valid Polygon for PostGIS storage.")
        row = dao.update_parking_area(parking_area_id, fields)
        if row is None:
            raise not_found("parking_area_id does not exist.")
        return self._response(row)

    def delete_parking_area(self, parking_area_id: int) -> dict:
        parking_area_id = require_positive_id(parking_area_id, "parking_area_id")
        dao = ParkingAreaDAO()
        if not dao.delete_parking_area(parking_area_id):
            raise not_found("parking_area_id does not exist.")
        return {"message": "Parking area deleted successfully.", "parking_area_id": parking_area_id}


# ---------- routes ----------
router = APIRouter(prefix="/parking-areas", tags=["Parking Areas"])


@router.post("", status_code=201)
def create_parking_area(payload: ParkingAreaCreate):
    return ParkingAreaHandler().create_parking_area(payload.model_dump())


@router.get("")
def list_parking_areas(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    name: str | None = None,
    bbox: str | None = None,
):
    return ParkingAreaHandler().list_parking_areas(limit, offset, name, bbox)


@router.get("/{parking_area_id}")
def get_parking_area(parking_area_id: int):
    return ParkingAreaHandler().get_parking_area(parking_area_id)


@router.put("/{parking_area_id}")
def update_parking_area(parking_area_id: int, payload: ParkingAreaUpdate):
    return ParkingAreaHandler().update_parking_area(parking_area_id, payload.model_dump(exclude_unset=True))


@router.delete("/{parking_area_id}")
def delete_parking_area(parking_area_id: int):
    return ParkingAreaHandler().delete_parking_area(parking_area_id)