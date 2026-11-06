from typing import Optional

from psycopg2 import errors as pg_errors

from backend.app.dao.vehicles import PlateNumberTaken, VehicleDAO
from backend.app.utils.timeutil import to_rfc3339
from backend.app.utils.validation import conflict, not_found


# ---------- response shapes (match the spec examples) ----------
def _vehicle_response(row: dict) -> dict:
    return {
        "vehicle_id": row["vehicle_id"],
        "vehicle_type_id": row["vehicle_type_id"],
        "vehicle_status_id": row["vehicle_status_id"],
        "plate_number": row["plate_number"],
        "make": row["make"],
        "model": row["model"],
        "year": row["year"],
        "created_at": to_rfc3339(row["created_at"]),
    }


def _list_item(row: dict) -> dict:
    return {
        "vehicle_id": row["vehicle_id"],
        "plate_number": row["plate_number"],
        "make": row["make"],
        "model": row["model"],
        "year": row["year"],
        "vehicle_type_id": row["vehicle_type_id"],
        "vehicle_status_id": row["vehicle_status_id"],
        "created_at": to_rfc3339(row["created_at"]),
    }


class VehicleService:
    def __init__(self):
        self.dao = VehicleDAO()

    def _require_references(self, vehicle_type_id=None, vehicle_status_id=None) -> None:
        if vehicle_type_id is not None and not self.dao.vehicle_type_exists(vehicle_type_id):
            raise not_found("vehicle_type_id does not exist.")
        if vehicle_status_id is not None and not self.dao.vehicle_status_exists(vehicle_status_id):
            raise not_found("vehicle_status_id does not exist.")

    # POST /api/v1/vehicles
    def create_vehicle(self, vehicle_type_id, vehicle_status_id, plate_number, make, model, year) -> dict:
        self._require_references(vehicle_type_id, vehicle_status_id)
        try:
            row = self.dao.create_vehicle(
                vehicle_type_id, vehicle_status_id, plate_number, make, model, year
            )
        except PlateNumberTaken:
            raise conflict("plate_number already exists.")
        except pg_errors.ForeignKeyViolation:  # type/status removed after the check above
            raise not_found("vehicle_type_id or vehicle_status_id does not exist.")
        return _vehicle_response(row)

    # GET /api/v1/vehicles
    def list_vehicles(
        self,
        limit: int,
        offset: int,
        plate_number: Optional[str],
        status_id: Optional[int],
        status_name: Optional[str],
    ) -> dict:
        rows, total = self.dao.get_vehicles(limit, offset, plate_number, status_id, status_name)
        return {
            "items": [_list_item(r) for r in rows],
            "limit": limit,
            "offset": offset,
            "count": total,  # matches before pagination
        }

    # GET /api/v1/vehicles/{vehicle_id}
    def get_vehicle(self, vehicle_id: int) -> dict:
        row = self.dao.get_vehicle_by_id(vehicle_id)
        if row is None:
            raise not_found("vehicle_id does not exist.")
        return _vehicle_response(row)

    # PUT /api/v1/vehicles/{vehicle_id}  (partial or full)
    def update_vehicle(self, vehicle_id: int, fields: dict) -> dict:
        if self.dao.get_vehicle_by_id(vehicle_id) is None:
            raise not_found("vehicle_id does not exist.")
        self._require_references(fields.get("vehicle_type_id"), fields.get("vehicle_status_id"))
        try:
            row = self.dao.update_vehicle(vehicle_id, fields)
        except PlateNumberTaken:
            raise conflict("plate_number already belongs to another vehicle.")
        except pg_errors.ForeignKeyViolation:
            raise not_found("vehicle_type_id or vehicle_status_id does not exist.")
        if row is None:  # deleted between the check above and the update
            raise not_found("vehicle_id does not exist.")
        return _vehicle_response(row)

    # DELETE /api/v1/vehicles/{vehicle_id}
    def delete_vehicle(self, vehicle_id: int) -> dict:
        if self.dao.get_vehicle_by_id(vehicle_id) is None:
            raise not_found("vehicle_id does not exist.")
        # No cascade deletes: pings, trips and assignments that use the vehicle block the delete.
        if self.dao.is_referenced(vehicle_id):
            raise conflict(
                "Vehicle is referenced by location pings, trips or assignments and cannot be deleted."
            )
        try:
            deleted = self.dao.delete_vehicle(vehicle_id)
        except pg_errors.ForeignKeyViolation:  # a reference was added after the check above
            raise conflict("Vehicle is referenced by other records and cannot be deleted.")
        if not deleted:
            raise not_found("vehicle_id does not exist.")
        return {"message": "Vehicle deleted successfully.", "vehicle_id": vehicle_id}

    # GET /api/v1/vehicles/{vehicle_id}/current-location
    def get_current_location(self, vehicle_id: int) -> Optional[dict]:
        """Returns None when the vehicle exists but has no pings (the handler turns that into 204)."""
        row = self.dao.get_current_location(vehicle_id)
        if row is None:
            raise not_found("vehicle_id does not exist.")
        if row["ping_id"] is None:
            return None
        return {
            "vehicle_id": row["vehicle_id"],
            "plate_number": row["plate_number"],
            "status": row["status"],
            "vehicle_kind": row["vehicle_kind"],
            "fuel_type": row["fuel_type"],
            "emissions_rating": row["emissions_rating"],
            "last_ts": to_rfc3339(row["last_ts"]),
            "last_geom": row["last_geom"],
            "speed_kph": row["speed_kph"],
            "heading_deg": row["heading_deg"],
        }
