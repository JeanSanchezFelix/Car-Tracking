import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor


class ParkingArea(BaseModel):
    parking_area_id: int | None = None
    name: str
    capacity: int | None = None
    geom: dict[str, Any]
    created_at: datetime | None = None


class ParkingAreaDAO:
    _DETAIL_COLUMNS = """
        parking_area_id, name, capacity,
        ST_AsGeoJSON(geom)::json AS geom, created_at
    """

    @staticmethod
    def _filters(
        *,
        name: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> tuple[list[str], list[Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if name is not None:
            conditions.append("name ILIKE %s")
            values.append(f"%{name}%")
        if bbox is not None:
            conditions.append(
                "ST_Intersects(geom, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            )
            values.extend(bbox)
        return conditions, values

    def create(self, area: ParkingArea) -> dict[str, Any]:
        """Insert a parking area and return the stored row."""
        with cursor() as cur:
            # The supplied table has no identity or sequence for this ID.
            cur.execute("LOCK TABLE parking_area IN EXCLUSIVE MODE")
            cur.execute(
                "SELECT COALESCE(MAX(parking_area_id), 0) + 1 AS parking_area_id "
                "FROM parking_area"
            )
            parking_area_id = cur.fetchone()["parking_area_id"]
            cur.execute(
                """
                INSERT INTO parking_area
                    (parking_area_id, name, capacity, geom, created_at)
                VALUES (
                    %s, %s, %s,
                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                    CURRENT_TIMESTAMP
                )
                RETURNING parking_area_id, name, capacity,
                          ST_AsGeoJSON(geom)::json AS geom, created_at
                """,
                (
                    parking_area_id,
                    area.name,
                    area.capacity,
                    json.dumps(area.geom),
                ),
            )
            return dict(cur.fetchone())

    def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        name: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> dict[str, Any]:
        conditions, filter_values = self._filters(name=name, bbox=bbox)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS count FROM parking_area{where}", filter_values
            )
            count = cur.fetchone()["count"]
            cur.execute(
                """
                SELECT parking_area_id, name, capacity, created_at
                FROM parking_area
                """
                + where
                + " ORDER BY parking_area_id LIMIT %s OFFSET %s",
                [*filter_values, limit, offset],
            )
            items = [dict(row) for row in cur.fetchall()]
        return {"items": items, "limit": limit, "offset": offset, "count": count}

    def get_by_id(self, parking_area_id: int) -> dict[str, Any] | None:
        with cursor() as cur:
            cur.execute(
                f"SELECT {self._DETAIL_COLUMNS} FROM parking_area "
                "WHERE parking_area_id = %s",
                (parking_area_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update(
        self, parking_area_id: int, fields: dict[str, Any]
    ) -> dict[str, Any] | None:
        allowed = {"name", "capacity", "geom"}
        if not fields:
            raise ValueError("At least one parking-area field must be provided")
        unknown = fields.keys() - allowed
        if unknown:
            raise ValueError(
                f"Unsupported parking-area fields: {', '.join(sorted(unknown))}"
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
        values.append(parking_area_id)

        with cursor() as cur:
            cur.execute(
                f"UPDATE parking_area SET {', '.join(assignments)} "
                f"WHERE parking_area_id = %s RETURNING {self._DETAIL_COLUMNS}",
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete(self, parking_area_id: int) -> bool:
        with cursor() as cur:
            cur.execute(
                "DELETE FROM parking_area WHERE parking_area_id = %s",
                (parking_area_id,),
            )
            return cur.rowcount == 1