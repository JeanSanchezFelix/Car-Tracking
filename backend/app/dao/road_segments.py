import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor
from backend.app.utils.validation import escape_like


class RoadSegment(BaseModel):
    road_id: int | None = None
    name: str
    speed_limit_kph: int | None = None
    geom: dict[str, Any]
    created_at: datetime | None = None
    is_oneway: bool | None = None
    direction: str | None = None


class RoadSegmentDAO:
    _DETAIL_COLUMNS = """
        road_id, name, speed_limit_kph, is_oneway, direction,
        ST_AsGeoJSON(geom)::json AS geom, created_at
    """

    @staticmethod
    def _filters(
        *,
        name: str | None = None,
        min_speed_kph: int | None = None,
        max_speed_kph: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if name is not None:
            conditions.append("name ILIKE %s")
            values.append(f"%{escape_like(name)}%")
        if min_speed_kph is not None:
            conditions.append("speed_limit_kph >= %s")
            values.append(min_speed_kph)
        if max_speed_kph is not None:
            conditions.append("speed_limit_kph <= %s")
            values.append(max_speed_kph)
        if bbox is not None:
            conditions.append(
                "ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            values.extend(bbox)
        return conditions, values

    def is_valid_geometry(self, geom: dict[str, Any]) -> bool:
        with cursor() as cur:
            cur.execute("SELECT ST_IsValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)) AS valid", (json.dumps(geom),))
            return cur.fetchone()["valid"]

    def create_road_segment(self, road: RoadSegment) -> dict[str, Any]:
        """Insert a road and return the stored row."""
        with cursor() as cur:
            # The supplied table has no identity or sequence for road_id.
            cur.execute("LOCK TABLE road_segment IN EXCLUSIVE MODE")
            cur.execute(
                "SELECT COALESCE(MAX(road_id), 0) + 1 AS road_id FROM road_segment"
            )
            road_id = cur.fetchone()["road_id"]
            cur.execute(
                """
                INSERT INTO road_segment
                    (road_id, name, speed_limit_kph, geom, created_at,
                     is_oneway, direction)
                VALUES (
                    %s, %s, %s,
                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                    date_trunc('second', now() AT TIME ZONE 'UTC'), %s, %s
                )
                RETURNING road_id, name, speed_limit_kph, is_oneway, direction,
                          ST_AsGeoJSON(geom)::json AS geom, created_at
                """,
                (
                    road_id,
                    road.name,
                    road.speed_limit_kph,
                    json.dumps(road.geom),
                    road.is_oneway,
                    road.direction,
                ),
            )
            return dict(cur.fetchone())

    def get_road_segments(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        name: str | None = None,
        min_speed_kph: int | None = None,
        max_speed_kph: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> dict[str, Any]:
        conditions, filter_values = self._filters(
            name=name,
            min_speed_kph=min_speed_kph,
            max_speed_kph=max_speed_kph,
            bbox=bbox,
        )
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS count FROM road_segment{where}", filter_values
            )
            count = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT road_id, name, speed_limit_kph, created_at,
                       is_oneway, direction
                FROM road_segment
                """
                + where
                + " ORDER BY road_id LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            )
            items = [dict(row) for row in cur.fetchall()]
        return {"items": items, "limit": limit, "offset": offset, "count": count}

    def get_road_segment_by_id(self, road_id: int) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                f"SELECT {self._DETAIL_COLUMNS} FROM road_segment WHERE road_id = %s",
                (road_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_road_segment(self, road_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {"name", "speed_limit_kph", "is_oneway", "direction", "geom"}
        if not fields:
            raise ValueError("At least one road-segment field must be provided")
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(
                f"Unsupported road-segment fields: {', '.join(sorted(unknown))}"
            )

        assignments: list[str] = []
        values: list[Any] = []
        for field, value in fields.items():
            if field == "geom":
                assignments.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)")
                values.append(json.dumps(value))
            else:
                assignments.append(f"{field} = %s")
                values.append(value)
        values.append(road_id)

        with cursor() as cur:
            cur.execute(
                f"UPDATE road_segment SET {', '.join(assignments)} "
                f"WHERE road_id = %s RETURNING {self._DETAIL_COLUMNS}",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_road_segment(self, road_id: int) -> bool:
        with cursor() as cur:
            cur.execute("DELETE FROM road_segment WHERE road_id = %s", (road_id,))
            return cur.rowcount == 1

    def get_road_segments_geojson(
        self,
        *,
        limit: int = 15000,
        offset: int = 0,
        name: str | None = None,
        min_speed_kph: int | None = None,
        max_speed_kph: int | None = None,
    ) -> dict[str, Any]:
        conditions, filter_values = self._filters(
            name=name,
            min_speed_kph=min_speed_kph,
            max_speed_kph=max_speed_kph,
        )
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS count FROM road_segment{where}", filter_values
            )
            count = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT road_id, name, speed_limit_kph, is_oneway, direction,
                       created_at, ST_AsGeoJSON(geom)::json AS geometry
                FROM road_segment
                """
                + where
                + " ORDER BY road_id LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            )
            items = [dict(row) for row in cur.fetchall()]
        return {"items": items, "limit": limit, "offset": offset, "count": count}
