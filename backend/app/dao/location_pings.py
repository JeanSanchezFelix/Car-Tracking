import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor


class LocationPing(BaseModel):
    ping_id: int | None = None
    vehicle_id: int
    ts: datetime
    geom: dict[str, Any]  # GeoJSON Point, [longitude, latitude]
    speed_kph: float | None = None
    heading_deg: float | None = None


# Columns a client may change with PUT. Used as a whitelist when building the UPDATE.
_UPDATABLE_COLUMNS = ("vehicle_id", "ts", "geom", "speed_kph", "heading_deg")


class LocationPingDAO:
    _DETAIL_COLUMNS = "ping_id, vehicle_id, ts, ST_AsGeoJSON(geom)::json AS geom, speed_kph, heading_deg"

    @staticmethod
    def _filters(vehicle_id, from_ts, to_ts, bbox):
        conditions = []
        params = {}
        if vehicle_id is not None:
            conditions.append("vehicle_id = %(vehicle_id)s")
            params["vehicle_id"] = vehicle_id
        if from_ts is not None:
            conditions.append("ts >= %(from_ts)s")
            params["from_ts"] = from_ts
        if to_ts is not None:
            conditions.append("ts <= %(to_ts)s")
            params["to_ts"] = to_ts
        if bbox is not None:
            conditions.append(
                "ST_Intersects(geom, ST_MakeEnvelope(%(min_lon)s, %(min_lat)s, %(max_lon)s, %(max_lat)s, 4326))"
            )
            params["min_lon"], params["min_lat"], params["max_lon"], params["max_lat"] = bbox
        return conditions, params

    def create_ping(self, new_ping: LocationPing) -> dict[str, Any]:
        """Inserts with ping_id = MAX + 1 and returns the stored ping."""
        query = f"""
        insert into
        location_ping (ping_id, vehicle_id, ts, geom, speed_kph, heading_deg)
        values (%(ping_id)s, %(vehicle_id)s, %(ts)s,
                ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326),
                %(speed_kph)s, %(heading_deg)s)
        returning {self._DETAIL_COLUMNS};
        """
        params = new_ping.model_dump()
        params["geom"] = json.dumps(params["geom"])  # PostGIS reads GeoJSON as text
        with cursor() as cur:
            cur.execute("LOCK TABLE location_ping IN EXCLUSIVE MODE")
            cur.execute("SELECT COALESCE(MAX(ping_id), 0) + 1 AS next_id FROM location_ping")
            params["ping_id"] = cur.fetchone()["next_id"]
            cur.execute(query, params)
            result = dict(cur.fetchone())
        return result

    def vehicle_exists(self, vehicle_id: int) -> bool:
        query = """
        select 1
        from vehicle
        where vehicle_id = %s
        """
        with cursor() as cur:
            cur.execute(query, (vehicle_id,))
            result = cur.fetchone() is not None
        return result

    def get_all_pings(self, limit: int, offset: int, vehicle_id: int | None = None,
                      from_ts: datetime | None = None, to_ts: datetime | None = None,
                      bbox: tuple | None = None, order_by_ts: bool = False) -> dict[str, Any]:
        """Return a page of pings and the total number of matches.
        from_ts/to_ts are inclusive; bbox is (minLon, minLat, maxLon, maxLat) and matches pings
        inside or on the edge of the box. total_matches is counted before limit/offset."""
        conditions, params = self._filters(vehicle_id, from_ts, to_ts, bbox)
        params.update(limit=limit, offset=offset)
        where = ("where " + " and ".join(conditions)) if conditions else ""
        order = "ts, ping_id" if order_by_ts else "ping_id"

        count_query = f"""
        select count(*) as total
        from location_ping
        {where}
        """
        query = f"""
        select {self._DETAIL_COLUMNS}
        from location_ping
        {where}
        order by {order}
        limit %(limit)s offset %(offset)s
        """
        with cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()["total"]
            cur.execute(query, params)
            result = [dict(row) for row in cur.fetchall()]
        return {"items": result, "limit": limit, "offset": offset, "count": total}

    def get_ping_by_id(self, ping_id: int) -> dict[str, Any] | None:
        query = f"""
        select {self._DETAIL_COLUMNS}
        from location_ping
        where ping_id = %s
        """
        with cursor() as cur:
            cur.execute(query, (ping_id,))
            row = cur.fetchone()
            result = dict(row) if row else None
        return result

    def get_pings_by_vehicle(self, vehicle_id: int, limit: int, offset: int,
                             from_ts: datetime | None = None,
                             to_ts: datetime | None = None) -> dict[str, Any]:
        """Return pings for one vehicle in time order."""
        return self.get_all_pings(limit, offset, vehicle_id=vehicle_id, from_ts=from_ts,
                                  to_ts=to_ts, order_by_ts=True)

    def update_ping(self, ping_id: int, fields: dict) -> dict[str, Any] | None:
        """Partial update: only the columns present in `fields` are changed.
        Returns the updated ping, or None if the ping does not exist."""
        sets = []
        params = {"ping_id": ping_id}
        for column in _UPDATABLE_COLUMNS:
            if column not in fields:
                continue
            if column == "geom":
                sets.append("geom = ST_SetSRID(ST_GeomFromGeoJSON(%(geom)s), 4326)")
                params["geom"] = json.dumps(fields["geom"])
            else:
                sets.append(f"{column} = %({column})s")
                params[column] = fields[column]
        query = f"""
        update location_ping
        set {", ".join(sets)}
        where ping_id = %(ping_id)s
        returning {self._DETAIL_COLUMNS}
        """
        with cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            result = dict(row) if row else None
        return result

    def delete_ping(self, ping_id: int) -> bool:
        query = """
        delete from location_ping
        where ping_id = %s
        """
        with cursor() as cur:
            cur.execute(query, (ping_id,))
            rows = cur.rowcount
        return rows == 1
