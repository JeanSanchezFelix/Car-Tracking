import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from backend.app.dao.connection import cursor


class Trip(BaseModel):
    trip_id: int | None = None
    vehicle_id: int
    start_ts: datetime
    end_ts: datetime
    start_geom: dict[str, Any] | None = None  # GeoJSON Point, [longitude, latitude]
    end_geom: dict[str, Any] | None = None
    distance_km: float | None = None


class TripIntervalInvalid(Exception):
    """The current stored interval would be invalid after applying an update."""


# Columns a client may change with PUT. Used as a whitelist when building the UPDATE.
_UPDATABLE_COLUMNS = ("vehicle_id", "start_ts", "end_ts", "start_geom", "end_geom", "distance_km")
_GEOM_COLUMNS = ("start_geom", "end_geom")


def _geom_param(geom: dict | None) -> str | None:
    """GeoJSON dict -> text for ST_GeomFromGeoJSON; None stays None (stored as NULL)."""
    return json.dumps(geom) if geom is not None else None


class TripDAO:
    _DETAIL_COLUMNS = """trip_id, vehicle_id, start_ts, end_ts,
        ST_AsGeoJSON(start_geom)::json AS start_geom,
        ST_AsGeoJSON(end_geom)::json AS end_geom, distance_km"""

    @staticmethod
    def _filters(vehicle_id, from_ts, to_ts):
        conditions = []
        params = {}
        if vehicle_id is not None:
            conditions.append("vehicle_id = %(vehicle_id)s")
            params["vehicle_id"] = vehicle_id
        if from_ts is not None:
            conditions.append("start_ts >= %(from_ts)s")
            params["from_ts"] = from_ts
        if to_ts is not None:
            conditions.append("start_ts <= %(to_ts)s")
            params["to_ts"] = to_ts
        return conditions, params

    def create_trip(self, new_trip: Trip) -> dict[str, Any]:
        """Inserts with trip_id = MAX + 1 and returns the stored trip."""
        query = f"""
        insert into
        trip (trip_id, vehicle_id, start_ts, end_ts, start_geom, end_geom, distance_km)
        values (%(trip_id)s, %(vehicle_id)s, %(start_ts)s, %(end_ts)s,
                ST_SetSRID(ST_GeomFromGeoJSON(%(start_geom)s), 4326),
                ST_SetSRID(ST_GeomFromGeoJSON(%(end_geom)s), 4326),
                %(distance_km)s)
        returning {self._DETAIL_COLUMNS};
        """
        params = new_trip.model_dump()
        for column in _GEOM_COLUMNS:
            params[column] = _geom_param(params[column])  # PostGIS reads GeoJSON as text
        with cursor() as cur:
            cur.execute("LOCK TABLE trip IN EXCLUSIVE MODE")
            cur.execute("SELECT COALESCE(MAX(trip_id), 0) + 1 AS next_id FROM trip")
            params["trip_id"] = cur.fetchone()["next_id"]
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

    def get_all_trips(self, limit: int, offset: int, vehicle_id: int | None = None,
                      from_ts: datetime | None = None, to_ts: datetime | None = None,
                      order_by_start: bool = False) -> dict[str, Any]:
        """Return a page of trips and the total number of matches.
        from_ts/to_ts select the trips that START inside [from_ts, to_ts] (inclusive).
        total_matches is counted before limit/offset."""
        conditions, params = self._filters(vehicle_id, from_ts, to_ts)
        params.update(limit=limit, offset=offset)
        where = ("where " + " and ".join(conditions)) if conditions else ""
        order = "start_ts, trip_id" if order_by_start else "trip_id"

        count_query = f"""
        select count(*) as total
        from trip
        {where}
        """
        query = f"""
        select {self._DETAIL_COLUMNS}
        from trip
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

    def get_trip_by_id(self, trip_id: int) -> dict[str, Any] | None:
        query = f"""
        select {self._DETAIL_COLUMNS}
        from trip
        where trip_id = %s
        """
        with cursor() as cur:
            cur.execute(query, (trip_id,))
            row = cur.fetchone()
            result = dict(row) if row else None
        return result

    def get_trips_by_vehicle(self, vehicle_id: int, limit: int, offset: int,
                             from_ts: datetime | None = None,
                             to_ts: datetime | None = None) -> dict[str, Any]:
        """Return trips for one vehicle in start-time order."""
        return self.get_all_trips(limit, offset, vehicle_id=vehicle_id, from_ts=from_ts,
                                  to_ts=to_ts, order_by_start=True)

    def update_trip(self, trip_id: int, fields: dict) -> dict[str, Any] | None:
        """Partial update: only the columns present in `fields` are changed.
        Returns the updated trip, or None if the trip does not exist.
        Raises TripIntervalInvalid if the interval fails the atomic SQL check."""
        sets = []
        params = {
            "trip_id": trip_id,
            "checked_start_ts": fields.get("start_ts"),
            "checked_end_ts": fields.get("end_ts"),
        }
        for column in _UPDATABLE_COLUMNS:
            if column not in fields:
                continue
            if column in _GEOM_COLUMNS:
                sets.append(f"{column} = ST_SetSRID(ST_GeomFromGeoJSON(%({column})s), 4326)")
                params[column] = _geom_param(fields[column])
            else:
                sets.append(f"{column} = %({column})s")
                params[column] = fields[column]
        query = f"""
        update trip
        set {", ".join(sets)}
        where trip_id = %(trip_id)s
          and COALESCE(%(checked_end_ts)s::timestamp, end_ts)
              > COALESCE(%(checked_start_ts)s::timestamp, start_ts)
        returning {self._DETAIL_COLUMNS}
        """
        with cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            if row is None:
                # The guarded UPDATE also checks the latest row after waiting for a writer.
                # Distinguish a failed interval check from a trip that does not exist.
                cur.execute("SELECT 1 FROM trip WHERE trip_id = %s", (trip_id,))
                if cur.fetchone() is not None:
                    raise TripIntervalInvalid()
            result = dict(row) if row else None
        return result

    def delete_trip(self, trip_id: int) -> bool:
        query = """
        delete from trip
        where trip_id = %s
        """
        with cursor() as cur:
            cur.execute(query, (trip_id,))
            rows = cur.rowcount
        return rows == 1
