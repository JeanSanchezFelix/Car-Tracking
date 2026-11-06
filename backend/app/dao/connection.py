import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

# --- Loads the .env ---
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")


def get_connection():
    """Opens a new connection to the database selected by DB_TARGET in the .env file."""
    """DB_TARGET="local" (default) uses the Docker DB, DB_TARGET="render" uses the Render DB."""
    """env.example shows the format of the .env file."""
    e = os.environ
    target = e.get("DB_TARGET", "local").lower()

    if target == "render":
        return psycopg2.connect(
            e["RENDER_URL"],
            user=e["RENDER_USER"],
            password=e["RENDER_PASSWORD"],
            sslmode="require",
        )
    if target == "local":
        return psycopg2.connect(
            host=e["LOCAL_HOST"],
            port=e["LOCAL_PORT"],
            user=e["LOCAL_USER"],
            password=e["LOCAL_PASSWORD"],
            dbname=e["LOCAL_DB"],
        )
    raise RuntimeError(f'DB_TARGET must be "local" or "render", got "{target}"')


@contextmanager
def transaction():
    """Everything run inside the with-block is committed together when it finishes, or rolled back if any error is raised."""
    """Database errors (e.g. psycopg2.errors.UniqueViolation, ForeignKeyViolation) are re-raised so the service layer can turn them into 409/404."""
    # --- Usage in a DAO ---
    #   with transaction() as cur:
    #       cur.execute("SELECT * FROM vehicle WHERE vehicle_id = %s", (vehicle_id,))
    #       return cur.fetchone()
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
