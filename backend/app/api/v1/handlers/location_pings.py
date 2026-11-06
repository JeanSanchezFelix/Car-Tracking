import json
import math
from typing import Any, Optional, Union

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, StrictStr

from backend.app.services.location_pings import LocationPingService
from backend.app.utils.geo import validate_geometry
from backend.app.utils.timeutil import parse_rfc3339
from backend.app.utils.validation import MAX_BIGINT, bad_request, parse_bbox, require_positive_id

router = APIRouter(prefix="/location-pings", tags=["Location Pings"])
# GET /vehicles/{vehicle_id}/pings lives under /vehicles but belongs to the ping resource.
vehicle_pings_router = APIRouter(prefix="/vehicles", tags=["Location Pings"])

Number = Union[StrictInt, StrictFloat]


# ---------- request bodies: a wrong shape (bad JSON, wrong types, unknown fields) is a 400 ----------
class PingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt
    ts: StrictStr
    geom: Any  # checked by validate_geometry so the error message names the problem
    speed_kph: Optional[Number] = None
    heading_deg: Optional[Number] = None


class PingUpdate(BaseModel):
    """Every field is optional: send only what you want to change."""

    model_config = ConfigDict(extra="forbid")
    vehicle_id: Optional[StrictInt] = None
    ts: Optional[StrictStr] = None
    geom: Any = None
    speed_kph: Optional[Number] = None
    heading_deg: Optional[Number] = None


# ---------- request validation (every rejection is a 400) ----------
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
        if speed is not None and not (math.isfinite(speed) and speed >= 0):
            raise bad_request("speed_kph must be greater than or equal to 0.")
        fields["speed_kph"] = speed
    if "heading_deg" in sent:
        heading = sent["heading_deg"]
        if heading is not None and not (math.isfinite(heading) and 0 <= heading < 360):
            raise bad_request("heading_deg must be >= 0 and < 360.")
        fields["heading_deg"] = heading
    return fields


def _time_range(from_ts: Optional[str], to_ts: Optional[str]) -> tuple:
    """Optional from_ts/to_ts filters: valid timestamps, and from_ts not later than to_ts."""
    start = parse_rfc3339(from_ts, "from_ts", assume_utc=True) if from_ts and from_ts.strip() else None
    end = parse_rfc3339(to_ts, "to_ts", assume_utc=True) if to_ts and to_ts.strip() else None
    if start is not None and end is not None and start > end:
        raise bad_request("from_ts must not be later than to_ts.")
    return start, end


# ---------- endpoints ----------
@router.post("", status_code=201)
def create_ping(payload: PingCreate):
    fields = _check_fields(payload.model_dump())
    return LocationPingService().create_ping(
        fields["vehicle_id"], fields["ts"], fields["geom"], fields["speed_kph"], fields["heading_deg"]
    )


@router.get("")
def list_pings(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    vehicle_id: Optional[int] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    bbox: Optional[str] = None,  # minLon,minLat,maxLon,maxLat
):
    if vehicle_id is not None:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    start, end = _time_range(from_ts, to_ts)
    box = parse_bbox(bbox) if bbox and bbox.strip() else None
    return LocationPingService().list_pings(limit, offset, vehicle_id, start, end, box)


@router.get("/{ping_id}")
def get_ping(ping_id: int):
    ping_id = require_positive_id(ping_id, "ping_id")
    return LocationPingService().get_ping(ping_id)


@router.put("/{ping_id}")
def update_ping(ping_id: int, payload: PingUpdate):
    ping_id = require_positive_id(ping_id, "ping_id")
    sent = payload.model_dump(exclude_unset=True)
    if not sent:
        raise bad_request("At least one updatable field must be supplied.")
    return LocationPingService().update_ping(ping_id, _check_fields(sent))


@router.delete("/{ping_id}")
def delete_ping(ping_id: int):
    ping_id = require_positive_id(ping_id, "ping_id")
    return LocationPingService().delete_ping(ping_id)


@vehicle_pings_router.get("/{vehicle_id}/pings")
def list_vehicle_pings(
    vehicle_id: int,
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
):
    vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
    start, end = _time_range(from_ts, to_ts)
    return LocationPingService().list_vehicle_pings(vehicle_id, limit, offset, start, end)
