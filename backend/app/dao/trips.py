class TripDAO:

    @staticmethod
    def _next_id(cur) -> int:
        """Returns the id for a new trip: the highest trip_id + 1 (or 1 if the table is empty)."""
        """The table has no identity or sequence for trip_id, so the DAO picks the id itself."""
        """LOCK keeps two requests from getting the same id; it is released when the transaction ends, so call this in the same `with cursor() as cur:` block as the INSERT."""
        cur.execute("LOCK TABLE trip IN EXCLUSIVE MODE")
        cur.execute("SELECT COALESCE(MAX(trip_id), 0) + 1 AS next_id FROM trip")
        return cur.fetchone()["next_id"]