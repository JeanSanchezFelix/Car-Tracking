from psycopg2 import sql

from backend.app.dao.connection import cursor
from backend.app.utils.validation import escape_like

# Columns a client may change with PUT. Used as a whitelist when building the UPDATE.
UPDATABLE_COLUMNS = ("vehicle_type_id", "vehicle_status_id", "plate_number", "make", "model", "year")

_RETURNING = sql.SQL(
    "vehicle_id, vehicle_type_id, vehicle_status_id, plate_number, make, model, year, created_at"
)


class PlateNumberTaken(Exception):
    """plate_number already belongs to another vehicle."""


class VehicleDAO:
    # ---------- lookups used by the service's business rules ----------
    def vehicle_type_exists(self, vehicle_type_id: int) -> bool:
        with cursor() as cur:
            cur.execute("SELECT 1 FROM vehicle_type WHERE vehicle_type_id = %s", (vehicle_type_id,))
            return cur.fetchone() is not None

    def vehicle_status_exists(self, vehicle_status_id: int) -> bool:
        with cursor() as cur:
            cur.execute(
                "SELECT 1 FROM vehicle_status WHERE vehicle_status_id = %s", (vehicle_status_id,)
            )
            return cur.fetchone() is not None

    def is_referenced(self, vehicle_id: int) -> bool:
        """True if pings, trips or assignments still point at this vehicle (no cascade deletes)."""
        with cursor() as cur:
            cur.execute(
                "SELECT (EXISTS (SELECT 1 FROM location_ping WHERE vehicle_id = %s) "
                "     OR EXISTS (SELECT 1 FROM trip WHERE vehicle_id = %s) "
                "     OR EXISTS (SELECT 1 FROM vehicle_assignment WHERE vehicle_id = %s)) AS referenced",
                (vehicle_id, vehicle_id, vehicle_id),
            )
            return cur.fetchone()["referenced"]

    @staticmethod
    def _lock_and_check_plate(cur, plate_number: str, exclude_vehicle_id=None) -> None:
        """Lock the table, then raise PlateNumberTaken if another vehicle has this plate."""
        cur.execute("LOCK TABLE vehicle IN SHARE ROW EXCLUSIVE MODE")
        cur.execute(
            "SELECT 1 FROM vehicle "
            "WHERE plate_number = %s AND (%s::bigint IS NULL OR vehicle_id <> %s::bigint)",
            (plate_number, exclude_vehicle_id, exclude_vehicle_id),
        )
        if cur.fetchone() is not None:
            raise PlateNumberTaken()

    # ---------- CRUD ----------
    def create_vehicle(self, vehicle_type_id, vehicle_status_id, plate_number, make, model, year):
        """Inserts with vehicle_id = MAX + 1. Raises PlateNumberTaken."""
        query = sql.SQL(
            "INSERT INTO vehicle "
            "(vehicle_id, vehicle_type_id, vehicle_status_id, plate_number, make, model, year, created_at) "
            "VALUES ((SELECT COALESCE(MAX(vehicle_id), 0) + 1 FROM vehicle), %s, %s, %s, %s, %s, %s, "
            "date_trunc('second', now() AT TIME ZONE 'UTC')) "
            "RETURNING {}"
        ).format(_RETURNING)
        with cursor() as cur:
            self._lock_and_check_plate(cur, plate_number)
            cur.execute(query, (vehicle_type_id, vehicle_status_id, plate_number, make, model, year))
            return cur.fetchone()

    def get_vehicle_by_id(self, vehicle_id: int):
        query = sql.SQL("SELECT {} FROM vehicle WHERE vehicle_id = %s").format(_RETURNING)
        with cursor() as cur:
            cur.execute(query, (vehicle_id,))
            return cur.fetchone()

    def get_vehicles(self, limit, offset, plate_number=None, status_id=None, status_name=None):
        """Returns (rows, total_matches). Filters are optional and combine with AND.
        plate_number is a case-insensitive partial match; status is an ID or a name."""
        conditions, params = [], []
        if plate_number is not None:
            conditions.append(sql.SQL("v.plate_number ILIKE %s"))
            params.append(f"%{escape_like(plate_number)}%")
        if status_id is not None:
            conditions.append(sql.SQL("v.vehicle_status_id = %s"))
            params.append(status_id)
        elif status_name is not None:
            conditions.append(sql.SQL("LOWER(vs.name) = LOWER(%s)"))
            params.append(status_name)
        where = (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conditions)) if conditions else sql.SQL("")

        count_query = sql.SQL(
            "SELECT COUNT(*) AS total FROM vehicle v "
            "LEFT JOIN vehicle_status vs ON vs.vehicle_status_id = v.vehicle_status_id{}"
        ).format(where)
        list_query = sql.SQL(
            "SELECT v.vehicle_id, v.vehicle_type_id, v.vehicle_status_id, v.plate_number, "
            "v.make, v.model, v.year, v.created_at FROM vehicle v "
            "LEFT JOIN vehicle_status vs ON vs.vehicle_status_id = v.vehicle_status_id{} "
            "ORDER BY v.vehicle_id LIMIT %s OFFSET %s"
        ).format(where)
        with cursor() as cur:
            cur.execute(count_query, params)
            total = cur.fetchone()["total"]
            cur.execute(list_query, params + [limit, offset])
            return cur.fetchall(), total

    def update_vehicle(self, vehicle_id: int, fields: dict):
        """Partial update: only the columns present in `fields` are touched.
        Returns None if the vehicle does not exist. Raises PlateNumberTaken."""
        columns = [c for c in UPDATABLE_COLUMNS if c in fields]
        assignments = [sql.SQL("{} = %s").format(sql.Identifier(c)) for c in columns]
        query = sql.SQL("UPDATE vehicle SET {} WHERE vehicle_id = %s RETURNING {}").format(
            sql.SQL(", ").join(assignments), _RETURNING
        )
        with cursor() as cur:
            if "plate_number" in fields:
                self._lock_and_check_plate(cur, fields["plate_number"], vehicle_id)
            cur.execute(query, [fields[c] for c in columns] + [vehicle_id])
            return cur.fetchone()

    def delete_vehicle(self, vehicle_id: int) -> bool:
        with cursor() as cur:
            cur.execute("DELETE FROM vehicle WHERE vehicle_id = %s RETURNING vehicle_id", (vehicle_id,))
            return cur.fetchone() is not None

    # ---------- current location ----------
    def get_current_location(self, vehicle_id: int):
        """One row for the vehicle with its most recent ping (ping columns are NULL if none)."""
        with cursor() as cur:
            cur.execute(
                "SELECT v.vehicle_id, v.plate_number, vs.name AS status, vk.name AS vehicle_kind, "
                "       ft.name AS fuel_type, vt.emissions_rating, "
                "       lp.ping_id, lp.ts AS last_ts, ST_AsGeoJSON(lp.geom)::json AS last_geom, "
                "       lp.speed_kph, lp.heading_deg "
                "FROM vehicle v "
                "LEFT JOIN vehicle_status vs ON vs.vehicle_status_id = v.vehicle_status_id "
                "LEFT JOIN vehicle_type vt ON vt.vehicle_type_id = v.vehicle_type_id "
                "LEFT JOIN vehicle_kind vk ON vk.vehicle_kind_id = vt.vehicle_kind_id "
                "LEFT JOIN fuel_type ft ON ft.fuel_type_id = vt.fuel_type_id "
                "LEFT JOIN LATERAL ("
                "    SELECT ping_id, ts, geom, speed_kph, heading_deg FROM location_ping "
                "    WHERE vehicle_id = v.vehicle_id ORDER BY ts DESC NULLS LAST, ping_id DESC LIMIT 1"
                ") lp ON TRUE "
                "WHERE v.vehicle_id = %s",
                (vehicle_id,),
            )
            return cur.fetchone()
