from psycopg2 import errors as pg_errors

from backend.app.dao.location_pings import LocationPing, LocationPingDAO
from backend.app.utils.timeutil import to_rfc3339
from backend.app.utils.validation import not_found


# ---------- response shapes (match the spec examples) ----------
def _ping_response(ping: LocationPing) -> dict:
    """POST, GET by id and PUT: the full ping, geometry included."""
    return {
        "ping_id": ping.ping_id,
        "vehicle_id": ping.vehicle_id,
        "ts": to_rfc3339(ping.ts),
        "geom": ping.geom,
        "speed_kph": ping.speed_kph,
        "heading_deg": ping.heading_deg,
    }


def _list_item(ping: LocationPing) -> dict:
    """GET /location-pings items: no geometry."""
    return {
        "ping_id": ping.ping_id,
        "vehicle_id": ping.vehicle_id,
        "ts": to_rfc3339(ping.ts),
        "speed_kph": ping.speed_kph,
        "heading_deg": ping.heading_deg,
    }


def _vehicle_ping_item(ping: LocationPing) -> dict:
    """GET /vehicles/{vehicle_id}/pings items: geometry included, vehicle_id is at the top level."""
    return {
        "ping_id": ping.ping_id,
        "ts": to_rfc3339(ping.ts),
        "geom": ping.geom,
        "speed_kph": ping.speed_kph,
        "heading_deg": ping.heading_deg,
    }


class LocationPingService:
    def __init__(self):
        self.dao = LocationPingDAO()

    def _require_vehicle(self, vehicle_id: int) -> None:
        if not self.dao.vehicle_exists(vehicle_id):
            raise not_found("vehicle_id does not exist.")

    # POST /api/v1/location-pings
    def create_ping(self, vehicle_id, ts, geom, speed_kph, heading_deg) -> dict:
        self._require_vehicle(vehicle_id)
        new_ping = LocationPing(
            vehicle_id=vehicle_id, ts=ts, geom=geom, speed_kph=speed_kph, heading_deg=heading_deg
        )
        try:
            ping = self.dao.create_ping(new_ping)
        except pg_errors.ForeignKeyViolation:  # vehicle removed after the check above
            raise not_found("vehicle_id does not exist.")
        return _ping_response(ping)

    # GET /api/v1/location-pings
    def list_pings(self, limit, offset, vehicle_id, from_ts, to_ts, bbox) -> dict:
        pings, total = self.dao.get_all_pings(limit, offset, vehicle_id, from_ts, to_ts, bbox)
        return {
            "items": [_list_item(p) for p in pings],
            "limit": limit,
            "offset": offset,
            "count": total,  # matches before pagination
        }

    # GET /api/v1/location-pings/{ping_id}
    def get_ping(self, ping_id: int) -> dict:
        ping = self.dao.get_ping_by_id(ping_id)
        if ping is None:
            raise not_found("ping_id does not exist.")
        return _ping_response(ping)

    # PUT /api/v1/location-pings/{ping_id}  (partial or full)
    def update_ping(self, ping_id: int, fields: dict) -> dict:
        if self.dao.get_ping_by_id(ping_id) is None:
            raise not_found("ping_id does not exist.")
        if "vehicle_id" in fields:
            self._require_vehicle(fields["vehicle_id"])
        try:
            ping = self.dao.update_ping(ping_id, fields)
        except pg_errors.ForeignKeyViolation:
            raise not_found("vehicle_id does not exist.")
        if ping is None:  # deleted between the check above and the update
            raise not_found("ping_id does not exist.")
        return _ping_response(ping)

    # DELETE /api/v1/location-pings/{ping_id}
    def delete_ping(self, ping_id: int) -> dict:
        if not self.dao.delete_ping(ping_id):
            raise not_found("ping_id does not exist.")
        return {"message": "Location ping deleted successfully.", "ping_id": ping_id}

    # GET /api/v1/vehicles/{vehicle_id}/pings
    def list_vehicle_pings(self, vehicle_id: int, limit, offset, from_ts, to_ts) -> dict:
        self._require_vehicle(vehicle_id)
        pings, total = self.dao.get_pings_by_vehicle(vehicle_id, limit, offset, from_ts, to_ts)
        return {
            "vehicle_id": vehicle_id,
            "items": [_vehicle_ping_item(p) for p in pings],
            "limit": limit,
            "offset": offset,
            "count": total,
        }