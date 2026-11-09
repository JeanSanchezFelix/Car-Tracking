import json
from typing import Any, Union

from fastapi import APIRouter, Query
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, StrictStr

from backend.app.dao.location_pings import LocationPing, LocationPingDAO
from backend.app.utils.geo import validate_geometry
from backend.app.utils.timeutil import parse_rfc3339, to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    is_finite_number,
    not_found,
    parse_bbox,
    require_positive_id,
)

Number = Union[StrictInt, StrictFloat]  # noqa: UP007


# ---------- request bodies: a wrong shape (bad JSON, wrong types, unknown fields) is a 400 ----------
class PingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt
    ts: StrictStr
    geom: Any  # checked by validate_geometry so the error message names the problem
    speed_kph: Number | None = None
    heading_deg: Number | None = None


class PingUpdate(BaseModel):
    """Every field is optional: send only what you want to change."""

    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt | None = None
    ts: StrictStr | None = None
    geom: Any = None
    speed_kph: Number | None = None
    heading_deg: Number | None = None


class LocationPingHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(ping: dict) -> dict:
        return {
            "ping_id": ping["ping_id"],
            "vehicle_id": ping["vehicle_id"],
            "ts": to_rfc3339(ping["ts"]),
            "geom": ping["geom"],
            "speed_kph": ping["speed_kph"],
            "heading_deg": ping["heading_deg"],
        }

    @staticmethod
    def _list_item(ping: dict) -> dict:
        """Collection items omit geometry."""
        return {
            "ping_id": ping["ping_id"],
            "vehicle_id": ping["vehicle_id"],
            "ts": to_rfc3339(ping["ts"]),
            "speed_kph": ping["speed_kph"],
            "heading_deg": ping["heading_deg"],
        }

    @staticmethod
    def _vehicle_ping_item(ping: dict) -> dict:
        """Vehicle-specific items include geometry; vehicle_id is at the top level."""
        return {
            "ping_id": ping["ping_id"],
            "ts": to_rfc3339(ping["ts"]),
            "geom": ping["geom"],
            "speed_kph": ping["speed_kph"],
            "heading_deg": ping["heading_deg"],
        }

    @staticmethod
    def _require_vehicle(dao: LocationPingDAO, vehicle_id: int) -> None:
        if not dao.vehicle_exists(vehicle_id):
            raise not_found("vehicle_id does not exist.")

    @staticmethod
    def _check_fields(sent: dict) -> dict:
        """Validate the ping fields present in `sent` (create sends all of them, update a subset).
        vehicle_id, ts and geom can never be null; speed_kph and heading_deg may be null."""
        fields = {}
        if "vehicle_id" in sent:
            fields["vehicle_id"] = require_positive_id(sent["vehicle_id"], "vehicle_id")
        if "ts" in sent:
            fields["ts"] = parse_rfc3339(sent["ts"], "ts", assume_utc=True)
        if "geom" in sent:
            fields["geom"] = json.loads(validate_geometry(sent["geom"], "Point", "geom"))  # checked GeoJSON Point
        if "speed_kph" in sent:
            speed = sent["speed_kph"]
            if speed is not None and not (is_finite_number(speed) and speed >= 0):
                raise bad_request("speed_kph must be greater than or equal to 0.")
            fields["speed_kph"] = speed
        if "heading_deg" in sent:
            heading = sent["heading_deg"]
            if heading is not None and not (is_finite_number(heading) and 0 <= heading < 360):
                raise bad_request("heading_deg must be >= 0 and < 360.")
            fields["heading_deg"] = heading
        return fields

    @staticmethod
    def _time_range(from_ts: str | None, to_ts: str | None) -> tuple:
        """Optional from_ts/to_ts filters: valid timestamps, and from_ts not later than to_ts."""
        start = parse_rfc3339(from_ts, "from_ts", assume_utc=True) if from_ts is not None else None
        end = parse_rfc3339(to_ts, "to_ts", assume_utc=True) if to_ts is not None else None
        if start is not None and end is not None and start > end:
            raise bad_request("from_ts must not be later than to_ts.")
        return start, end

    # ---------- endpoints ----------
    def create_ping(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        dao = LocationPingDAO()
        self._require_vehicle(dao, fields["vehicle_id"])
        try:
            ping = dao.create_ping(LocationPing(**fields))
        except pg_errors.ForeignKeyViolation:  # vehicle removed after the check above
            raise not_found("vehicle_id does not exist.")
        return self._response(ping)

    def list_pings(self, limit, offset, vehicle_id, from_ts, to_ts, bbox) -> dict:
        if vehicle_id is not None:
            vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        start, end = self._time_range(from_ts, to_ts)
        box = parse_bbox(bbox) if bbox is not None else None
        dao = LocationPingDAO()
        result = dao.get_all_pings(limit, offset, vehicle_id, start, end, box)
        return {
            "items": [self._list_item(p) for p in result["items"]],
            "limit": limit,
            "offset": offset,
            "count": result["count"],
        }

    def list_vehicle_pings(self, vehicle_id, limit, offset, from_ts, to_ts) -> dict:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        start, end = self._time_range(from_ts, to_ts)
        dao = LocationPingDAO()
        self._require_vehicle(dao, vehicle_id)
        result = dao.get_pings_by_vehicle(vehicle_id, limit, offset, start, end)
        return {
            "vehicle_id": vehicle_id,
            "items": [self._vehicle_ping_item(p) for p in result["items"]],
            "limit": limit,
            "offset": offset,
            "count": result["count"],
        }

    def get_ping(self, ping_id: int) -> dict:
        ping_id = require_positive_id(ping_id, "ping_id")
        dao = LocationPingDAO()
        ping = dao.get_ping_by_id(ping_id)
        if ping is None:
            raise not_found("ping_id does not exist.")
        return self._response(ping)

    def update_ping(self, ping_id: int, sent: dict) -> dict:
        ping_id = require_positive_id(ping_id, "ping_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)
        dao = LocationPingDAO()
        if dao.get_ping_by_id(ping_id) is None:
            raise not_found("ping_id does not exist.")
        if "vehicle_id" in fields:
            self._require_vehicle(dao, fields["vehicle_id"])
        try:
            ping = dao.update_ping(ping_id, fields)
        except pg_errors.ForeignKeyViolation:
            raise not_found("vehicle_id does not exist.")
        if ping is None:  # deleted between the check above and the update
            raise not_found("ping_id does not exist.")
        return self._response(ping)

    def delete_ping(self, ping_id: int) -> dict:
        ping_id = require_positive_id(ping_id, "ping_id")
        dao = LocationPingDAO()
        if not dao.delete_ping(ping_id):
            raise not_found("ping_id does not exist.")
        return {"message": "Location ping deleted successfully.", "ping_id": ping_id}


# ---------- routes ----------
router = APIRouter(prefix="/location-pings", tags=["Location Pings"])
# GET /vehicles/{vehicle_id}/pings lives under /vehicles but belongs to the ping resource.
vehicle_pings_router = APIRouter(prefix="/vehicles", tags=["Location Pings"])


@router.post("", status_code=201)
def create_ping(payload: PingCreate):
    return LocationPingHandler().create_ping(payload.model_dump())


@router.get("")
def list_pings(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    vehicle_id: int | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    bbox: str | None = None,  # minLon,minLat,maxLon,maxLat
):
    return LocationPingHandler().list_pings(limit, offset, vehicle_id, from_ts, to_ts, bbox)


@router.get("/{ping_id}")
def get_ping(ping_id: int):
    return LocationPingHandler().get_ping(ping_id)


@router.put("/{ping_id}")
def update_ping(ping_id: int, payload: PingUpdate):
    return LocationPingHandler().update_ping(ping_id, payload.model_dump(exclude_unset=True))


@router.delete("/{ping_id}")
def delete_ping(ping_id: int):
    return LocationPingHandler().delete_ping(ping_id)


@vehicle_pings_router.get("/{vehicle_id}/pings")
def get_vehicle_pings(
    vehicle_id: int,
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    return LocationPingHandler().list_vehicle_pings(vehicle_id, limit, offset, from_ts, to_ts)
