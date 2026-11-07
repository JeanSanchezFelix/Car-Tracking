from collections.abc import Generator
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock

from psycopg2.extras import DictCursor
from psycopg2.pool import ThreadedConnectionPool

from backend.app.config.dbconfig import PG_DB_CONFIG, POOL_CONFIG

_pool: ThreadedConnectionPool | None = None
_pool_lock = Lock()
# psycopg2's pool raises PoolError when every connection is in use. One slot per connection
# makes a request wait for a free connection instead of failing with a 500.
_free_connections = BoundedSemaphore(POOL_CONFIG["maxconn"])

def get_pool() -> ThreadedConnectionPool:
    """Create the shared pool once and return it."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    POOL_CONFIG["minconn"],
                    POOL_CONFIG["maxconn"],
                    **PG_DB_CONFIG,
                )
    return _pool

@contextmanager
def cursor() -> Generator[DictCursor, None, None]:
    """Borrow a pooled connection and cursor for one transaction."""
    pool = get_pool()
    with _free_connections:
        conn = pool.getconn()
        try:
            with conn.cursor(cursor_factory=DictCursor) as db_cursor:
                yield db_cursor
            conn.commit()
        except Exception:
            if not conn.closed:  # rollback() on a dropped connection would raise and hide the real error
                conn.rollback()
            raise
        finally:
            pool.putconn(conn)  # psycopg2 discards connections the server already closed