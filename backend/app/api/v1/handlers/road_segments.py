import json
from typing import Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from backend.app.dao.road_segments import RoadSegment, RoadSegmentDAO
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
class RoadSegmentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr
    speed_limit_kph: StrictInt | None = None
    geom: Any
    is_oneway: StrictBool | None = None
    direction: StrictStr | None = None


class RoadSegmentUpdate(BaseModel):
    """Send only the fields to change."""

    model_config = ConfigDict(extra="forbid")
    name: StrictStr | None = None
    speed_limit_kph: StrictInt | None = None
    geom: Any = None
    is_oneway: StrictBool | None = None
    direction: StrictStr | None = None


class RoadSegmentHandler:
    # ---------- helpers ----------
    @staticmethod
    def _response(row: dict, *, include_geom: bool = True, include_direction: bool = False) -> dict:
        result = {
            "road_id": row["road_id"],
            "name": row["name"],
            "speed_limit_kph": row["speed_limit_kph"],
            "created_at": to_rfc3339(row["created_at"]),
        }
        if include_geom:
            result["geom"] = row["geom"]
        if include_direction:
            result["is_oneway"] = row["is_oneway"]
            result["direction"] = row["direction"]
        return result

    @staticmethod
    def _check_fields(sent: dict) -> dict:
        fields = {}
        if "name" in sent:
            fields["name"] = clean_text(sent["name"], "name", required=True)
        if "speed_limit_kph" in sent:
            value = sent["speed_limit_kph"]
            fields["speed_limit_kph"] = None if value is None else require_non_negative_int(value, "speed_limit_kph")
        if "geom" in sent:
            fields["geom"] = json.loads(validate_geometry(sent["geom"], "LineString"))
        if "is_oneway" in sent:
            fields["is_oneway"] = sent["is_oneway"]
        if "direction" in sent:
            value = clean_text(sent["direction"], "direction")
            if value is not None and value not in ("both", "forward"):
                raise bad_request("direction must be both or forward.")
            fields["direction"] = value
        return fields

    @staticmethod
    def _check_speed_range(min_speed_kph: int | None, max_speed_kph: int | None) -> None:
        if min_speed_kph is not None and max_speed_kph is not None and min_speed_kph > max_speed_kph:
            raise bad_request("min_speed_kph must not exceed max_speed_kph.")

    # ---------- endpoints ----------
    def create_road_segment(self, sent: dict) -> dict:
        fields = self._check_fields(sent)
        dao = RoadSegmentDAO()
        if not dao.is_valid_geometry(fields["geom"]):
            raise bad_request("geom must be a valid LineString for PostGIS storage.")
        row = dao.create_road_segment(RoadSegment(**fields))
        return self._response(row, include_direction=True)

    def list_road_segments(
        self, limit: int, offset: int, name: str | None,
        min_speed_kph: int | None, max_speed_kph: int | None, bbox: str | None,
    ) -> dict:
        name = clean_text(name, "name") or None
        self._check_speed_range(min_speed_kph, max_speed_kph)
        box = parse_bbox(bbox) if bbox is not None else None
        dao = RoadSegmentDAO()
        result = dao.get_road_segments(
            limit=limit, offset=offset, name=name,
            min_speed_kph=min_speed_kph, max_speed_kph=max_speed_kph, bbox=box,
        )
        result["items"] = [self._response(row, include_geom=False) for row in result["items"]]
        return result

    def get_road_segment(self, road_id: int) -> dict:
        road_id = require_positive_id(road_id, "road_id")
        dao = RoadSegmentDAO()
        row = dao.get_road_segment_by_id(road_id)
        if row is None:
            raise not_found("road_id does not exist.")
        return self._response(row)

    def update_road_segment(self, road_id: int, sent: dict) -> dict:
        road_id = require_positive_id(road_id, "road_id")
        if not sent:
            raise bad_request("At least one updatable field must be supplied.")
        fields = self._check_fields(sent)
        dao = RoadSegmentDAO()
        if "geom" in fields and not dao.is_valid_geometry(fields["geom"]):
            raise bad_request("geom must be a valid LineString for PostGIS storage.")
        row = dao.update_road_segment(road_id, fields)
        if row is None:
            raise not_found("road_id does not exist.")
        return self._response(row)

    def delete_road_segment(self, road_id: int) -> dict:
        road_id = require_positive_id(road_id, "road_id")
        dao = RoadSegmentDAO()
        if not dao.delete_road_segment(road_id):
            raise not_found("road_id does not exist.")
        return {"message": "Road segment deleted successfully.", "road_id": road_id}

    def get_road_segments_geojson(
        self, limit: int, offset: int, name: str | None,
        min_speed_kph: int | None, max_speed_kph: int | None, bbox: str | None,
    ) -> dict:
        if bbox is not None:
            raise bad_request("This endpoint does not accept a bbox parameter.")
        name = clean_text(name, "name") or None
        self._check_speed_range(min_speed_kph, max_speed_kph)
        dao = RoadSegmentDAO()
        result = dao.get_road_segments_geojson(
            limit=limit, offset=offset, name=name,
            min_speed_kph=min_speed_kph, max_speed_kph=max_speed_kph,
        )
        return {
            "type": "FeatureCollection",
            "count": result["count"],
            "limit": result["limit"],
            "offset": result["offset"],
            "features": [
                {
                    "type": "Feature",
                    "geometry": row["geometry"],
                    "properties": self._response(row, include_geom=False, include_direction=True),
                }
                for row in result["items"]
            ],
        }


# ---------- routes ----------
router = APIRouter(prefix="/road-segments", tags=["Road Segments"])


@router.post("", status_code=201)
def create_road_segment(payload: RoadSegmentCreate):
    return RoadSegmentHandler().create_road_segment(payload.model_dump())


@router.get("")
def list_road_segments(
    limit: int = Query(20, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    name: str | None = None,
    min_speed_kph: int | None = Query(None, ge=0, le=MAX_BIGINT),
    max_speed_kph: int | None = Query(None, ge=0, le=MAX_BIGINT),
    bbox: str | None = None,
):
    return RoadSegmentHandler().list_road_segments(limit, offset, name, min_speed_kph, max_speed_kph, bbox)


# Register the literal path before /{road_id} so geojson is not parsed as an ID.
@router.get("/geojson", response_class=Response, responses={200: {"content": {"application/geo+json": {}}}})
def get_road_segments_geojson(
    limit: int = Query(15000, ge=0, le=MAX_BIGINT),
    offset: int = Query(0, ge=0, le=MAX_BIGINT),
    name: str | None = None,
    min_speed_kph: int | None = Query(None, ge=0, le=MAX_BIGINT),
    max_speed_kph: int | None = Query(None, ge=0, le=MAX_BIGINT),
    bbox: str | None = Query(None, include_in_schema=False),
):
    result = RoadSegmentHandler().get_road_segments_geojson(
        limit, offset, name, min_speed_kph, max_speed_kph, bbox
    )
    return JSONResponse(content=result, media_type="application/geo+json")


@router.get("/{road_id}")
def get_road_segment(road_id: int):
    return RoadSegmentHandler().get_road_segment(road_id)


@router.put("/{road_id}")
def update_road_segment(road_id: int, payload: RoadSegmentUpdate):
    return RoadSegmentHandler().update_road_segment(road_id, payload.model_dump(exclude_unset=True))


@router.delete("/{road_id}")
def delete_road_segment(road_id: int):
    return RoadSegmentHandler().delete_road_segment(road_id)