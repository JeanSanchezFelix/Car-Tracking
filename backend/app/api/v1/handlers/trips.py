import json
import math
from typing import Any, Union

from fastapi import APIRouter, Query
from psycopg2 import errors as pg_errors
from pydantic import BaseModel, ConfigDict, StrictFloat, StrictInt, StrictStr

from backend.app.dao.trips import Trip, TripDAO
from backend.app.utils.geo import validate_geometry
from backend.app.utils.timeutil import parse_rfc3339, to_rfc3339
from backend.app.utils.validation import (
    MAX_BIGINT,
    bad_request,
    not_found,
    require_later,
    require_positive_id,
)

Number = Union[StrictInt, StrictFloat]  # noqa: UP007


# ---------- request bodies: a wrong shape (bad JSON, wrong types, unknown fields) is a 400 ----------
class TripCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt
    start_ts: StrictStr
    end_ts: StrictStr
    start_geom: Any = None  # optional; checked by validate_geometry when present
    end_geom: Any = None
    distance_km: Number | None = None


class TripUpdate(BaseModel):
    """Every field is optional: send only what you want to change."""

    model_config = ConfigDict(extra="forbid")
    vehicle_id: StrictInt | None = None
    start_ts: StrictStr | None = None
    end_ts: StrictStr | None = None
    start_geom: Any = None
    end_geom: Any = None
    distance_km: Number | None = None


class TripHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(trip: Trip) -> dict:
        return {
            "trip_id": trip.trip_id,
            "vehicle_id": trip.vehicle_id,
            "start_ts": to_rfc3339(trip.start_ts),
            "end_ts": to_rfc3339(trip.end_ts),
            "start_geom": trip.start_geom,
            "end_geom": trip.end_geom,
            "distance_km": trip.distance_km,
        }

    @staticmethod
    def _list_item(trip: Trip) -> dict:
        """Collection items omit geometries."""
        return {
            "trip_id": trip.trip_id,
            "vehicle_id": trip.vehicle_id,
            "start_ts": to_rfc3339(trip.start_ts),
            "end_ts": to_rfc3339(trip.end_ts),
            "distance_km": trip.distance_km,
        }

    @staticmethod
    def _vehicle_trip_item(trip: Trip) -> dict:
        """Vehicle-specific items omit geometries; vehicle_id is at the top level."""
        return {
            "trip_id": trip.trip_id,
            "start_ts": to_rfc3339(trip.start_ts),
            "end_ts": to_rfc3339(trip.end_ts),
            "distance_km": trip.distance_km,
        }

    @staticmethod
    def _require_vehicle(dao: TripDAO, vehicle_id: int) -> None:
        if not dao.vehicle_exists(vehicle_id):
            raise not_found("vehicle_id does not exist.")

    @staticmethod
    def _check_fields(sent: dict) -> dict:
        """Validate the trip fields present in `sent` (create sends all of them, update a subset).
        vehicle_id, start_ts and end_ts can never be null; the geometries and distance_km may be null."""
        fields = {}
        if "vehicle_id" in sent:
            fields["vehicle_id"] = require_positive_id(sent["vehicle_id"], "vehicle_id")
        for column in ("start_ts", "end_ts"):
            if column in sent:
                fields[column] = parse_rfc3339(sent[column], column, assume_utc=True)
        for column in ("start_geom", "end_geom"):  # optional Points, stored in SRID 4326
            if column in sent:
                geom = sent[column]
                fields[column] = None if geom is None else json.loads(validate_geometry(geom, "Point", column))
        if "distance_km" in sent:
            distance = sent["distance_km"]
            if distance is not None and not (math.isfinite(distance) and distance >= 0):
                raise bad_request("distance_km must be greater than or equal to 0.")
            fields["distance_km"] = distance
        return fields

    @staticmethod
    def _time_range(from_ts: str | None, to_ts: str | None) -> tuple:
        """Optional from_ts/to_ts filters: valid timestamps, and from_ts not later than to_ts."""
        start = parse_rfc3339(from_ts, "from_ts", assume_utc=True) if from_ts and from_ts.strip() else None
        end = parse_rfc3339(to_ts, "to_ts", assume_utc=True) if to_ts and to_ts.strip() else None
        if start is not None and end is not None and start > end:
            raise bad_request("from_ts must not be later than to_ts.")
        return start, end

    # ---------- endpoints ----------
    def create_trip(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        # POST only documents 201/400/404, so a reversed interval is a 400 here
        require_later(fields["start_ts"], fields["end_ts"], "start_ts", "end_ts", status_code=400)
        dao = TripDAO()
        self._require_vehicle(dao, fields["vehicle_id"])
        try:
            trip = dao.create_trip(Trip(**fields))
        except pg_errors.ForeignKeyViolation:  # vehicle removed after the check above
            raise not_found("vehicle_id does not exist.")
        return self._response(trip)

    def list_trips(self, limit, offset, vehicle_id, from_ts, to_ts) -> dict:
        if vehicle_id is not None:
            vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        start, end = self._time_range(from_ts, to_ts)
        dao = TripDAO()
        trips, total = dao.get_all_trips(limit, offset, vehicle_id, start, end)
        return {
            "items": [self._list_item(t) for t in trips],
            "limit": limit,
            "offset": offset,
            "count": total,
        }

    def list_vehicle_trips(self, vehicle_id, limit, offset, from_ts, to_ts) -> dict:
        vehicle_id = require_positive_id(vehicle_id, "vehicle_id")
        start, end = self._time_range(from_ts, to_ts)
        dao = TripDAO()
        self._require_vehicle(dao, vehicle_id)
        trips, total = dao.get_trips_by_vehicle(vehicle_id, limit, offset, start, end)
        return {
            "vehicle_id": vehicle_id,
            "items": [self._vehicle_trip_item(t) for t in trips],
            "limit": limit,
            "offset": offset,
            "count": total,
        }

    def get_trip(self, trip_id: int) -> dict:
        trip_id = require_positive_id(trip_id, "trip_id")
        dao = TripDAO()
        trip = dao.get_trip_by_id(trip_id)
        if trip is None:
            raise not_found("trip_id does not exist.")
        return self._response(trip)

    def update_trip(self, trip_id: int, sent: dict) -> dict:
        trip_id = require_positive_id(trip_id, "trip_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)
        dao = TripDAO()
        current = dao.get_trip_by_id(trip_id)
        if current is None:
            raise not_found("trip_id does not exist.")
        if "vehicle_id" in fields:
            self._require_vehicle(dao, fields["vehicle_id"])
        # The interval is checked on the trip as it will look after the update (422 if invalid).
        start_ts = fields.get("start_ts", current.start_ts)
        end_ts = fields.get("end_ts", current.end_ts)
        require_later(start_ts, end_ts, "start_ts", "end_ts")
        try:
            trip = dao.update_trip(trip_id, fields)
        except pg_errors.ForeignKeyViolation:
            raise not_found("vehicle_id does not exist.")
        if trip is None:  # deleted between the check above and the update
            raise not_found("trip_id does not exist.")
        return self._response(trip)

    def delete_trip(self, trip_id: int) -> dict:
        trip_id = require_positive_id(trip_id, "trip_id")
        dao = TripDAO()
        if not dao.delete_trip(trip_id):
            raise not_found("trip_id does not exist.")
        return {"message": "Trip deleted successfully.", "trip_id": trip_id}


# ---------- routes ----------
router = APIRouter(prefix="/trips", tags=["Trips"])
# GET /vehicles/{vehicle_id}/trips lives under /vehicles but belongs to the trip resource.
vehicle_trips_router = APIRouter(prefix="/vehicles", tags=["Trips"])


@router.post("", status_code=201)
def create_trip(payload: TripCreate):
    return TripHandler().create_trip(payload.model_dump())


@router.get("")
def list_trips(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    vehicle_id: int | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    return TripHandler().list_trips(limit, offset, vehicle_id, from_ts, to_ts)


@router.get("/{trip_id}")
def get_trip(trip_id: int):
    return TripHandler().get_trip(trip_id)


@router.put("/{trip_id}")
def update_trip(trip_id: int, payload: TripUpdate):
    return TripHandler().update_trip(trip_id, payload.model_dump(exclude_unset=True))


@router.delete("/{trip_id}")
def delete_trip(trip_id: int):
    return TripHandler().delete_trip(trip_id)


@vehicle_trips_router.get("/{vehicle_id}/trips")
def get_vehicle_trips(
    vehicle_id: int,
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    from_ts: str | None = None,
    to_ts: str | None = None,
):
    return TripHandler().list_vehicle_trips(vehicle_id, limit, offset, from_ts, to_ts)
