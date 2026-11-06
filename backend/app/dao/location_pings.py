class LocationPingDAO:

    @staticmethod
    def _next_id(cur) -> int:
        """Returns the id for a new ping: the highest ping_id + 1 (or 1 if the table is empty)."""
        """The table has no identity or sequence for ping_id, so the DAO picks the id itself."""
        """LOCK keeps two requests from getting the same id; it is released when the transaction ends, so call this in the same `with cursor() as cur:` block as the INSERT."""
        cur.execute("LOCK TABLE location_ping IN EXCLUSIVE MODE")
        cur.execute("SELECT COALESCE(MAX(ping_id), 0) + 1 AS next_id FROM location_ping")
        return cur.fetchone()["next_id"]
