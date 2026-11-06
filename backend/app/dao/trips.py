import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel

from backend.app.dao.connection import cursor


class Trip(BaseModel):
    trip_id: Optional[int] = None
    vehicle_id: int
    start_ts: datetime
    end_ts: datetime
    start_geom: Optional[dict[str, Any]] = None  # GeoJSON Point, [longitude, latitude]
    end_geom: Optional[dict[str, Any]] = None
    distance_km: Optional[float] = None


# Columns returned by every query; ST_AsGeoJSON turns the PostGIS geometries back into GeoJSON
_COLUMNS = """trip_id, vehicle_id, start_ts, end_ts,
        ST_AsGeoJSON(start_geom)::json AS start_geom,
        ST_AsGeoJSON(end_geom)::json AS end_geom,
        distance_km"""

# Columns a client may change with PUT. Used as a whitelist when building the UPDATE.
_UPDATABLE_COLUMNS = ("vehicle_id", "start_ts", "end_ts", "start_geom", "end_geom", "distance_km")
_GEOM_COLUMNS = ("start_geom", "end_geom")


def _geom_param(geom: Optional[dict]) -> Optional[str]:
    """GeoJSON dict -> text for ST_GeomFromGeoJSON; None stays None (stored as NULL)."""
    return json.dumps(geom) if geom is not None else None


class TripDAO:
    # Every method borrows a pooled connection and a DictCursor with `with cursor() as cur:`.
    # When the block ends the change is committed, the cursor closed and the connection returned
    # to the pool; if anything fails it is rolled back and the connection is still returned.

    @staticmethod
    def _next_id(cur) -> int:
        """Returns the id for a new trip: the highest trip_id + 1 (or 1 if the table is empty)."""
        """The table has no identity or sequence for trip_id, so the DAO picks the id itself."""
        """LOCK keeps two requests from getting the same id; it is released when the transaction ends, so call this in the same `with cursor() as cur:` block as the INSERT."""
        cur.execute("LOCK TABLE trip IN EXCLUSIVE MODE")
        cur.execute("SELECT COALESCE(MAX(trip_id), 0) + 1 AS next_id FROM trip")
        return cur.fetchone()["next_id"]

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

    def get_all_trips(self, limit: int, offset: int, vehicle_id: Optional[int] = None,
                      from_ts: Optional[datetime] = None, to_ts: Optional[datetime] = None,
                      order_by_start: bool = False) -> tuple[list[Trip], int]:
        """Returns (trips, total_matches). Filters are optional and combine with AND.
        from_ts/to_ts select the trips that START inside [from_ts, to_ts] (inclusive).
        total_matches is counted before limit/offset."""
        conditions = []
        params = {"limit": limit, "offset": offset}
        if vehicle_id is not None:
            conditions.append("vehicle_id = %(vehicle_id)s")
            params["vehicle_id"] = vehicle_id
        if from_ts is not None:
            conditions.append("start_ts >= %(from_ts)s")
            params["from_ts"] = from_ts
        if to_ts is not None:
            conditions.append("start_ts <= %(to_ts)s")
            params["to_ts"] = to_ts
        where = ("where " + " and ".join(conditions)) if conditions else ""
        order = "start_ts, trip_id" if order_by_start else "trip_id"

        count_query = f"""
        select count(*) as total
        from trip
        {where}
        """
        query = f"""
        select {_COLUMNS}
        from trip
        {where}
        order by {order}
        limit %(limit)s offset %(offset)s
        """
        with cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()["total"]
            cur.execute(query, params)
            result: list[Trip] = []
            for row in cur:
                result.append(Trip(**row))
        return result, total

    def get_trip_by_id(self, trip_id: int) -> Optional[Trip]:
        query = f"""
        select {_COLUMNS}
        from trip
        where trip_id = %s
        """
        with cursor() as cur:
            cur.execute(query, (trip_id,))
            row = cur.fetchone()
            result: Optional[Trip] = Trip(**row) if row else None
        return result

    def get_trips_by_vehicle(self, vehicle_id: int, limit: int, offset: int,
                             from_ts: Optional[datetime] = None,
                             to_ts: Optional[datetime] = None) -> tuple[list[Trip], int]:
        """Trips of one vehicle in start-time order. Returns (trips, total_matches)."""
        return self.get_all_trips(limit, offset, vehicle_id=vehicle_id, from_ts=from_ts,
                                  to_ts=to_ts, order_by_start=True)

    def create_trip(self, new_trip: Trip) -> Trip:
        """Inserts with trip_id = MAX + 1 and returns the stored trip."""
        query = f"""
        insert into
        trip (trip_id, vehicle_id, start_ts, end_ts, start_geom, end_geom, distance_km)
        values (%(trip_id)s, %(vehicle_id)s, %(start_ts)s, %(end_ts)s,
                ST_SetSRID(ST_GeomFromGeoJSON(%(start_geom)s), 4326),
                ST_SetSRID(ST_GeomFromGeoJSON(%(end_geom)s), 4326),
                %(distance_km)s)
        returning {_COLUMNS};
        """
        params = new_trip.model_dump()
        for column in _GEOM_COLUMNS:
            params[column] = _geom_param(params[column])  # PostGIS reads GeoJSON as text
        with cursor() as cur:
            params["trip_id"] = self._next_id(cur)
            cur.execute(query, params)
            result = Trip(**cur.fetchone())
        return result

    def update_trip(self, trip_id: int, fields: dict) -> Optional[Trip]:
        """Partial update: only the columns present in `fields` are changed.
        Returns the updated trip, or None if the trip does not exist."""
        sets = []
        params = {"trip_id": trip_id}
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
        returning {_COLUMNS}
        """
        with cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            result: Optional[Trip] = Trip(**row) if row else None
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
