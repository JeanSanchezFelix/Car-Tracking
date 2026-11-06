import os

from dotenv import load_dotenv

# Load the repository's local .env when running the API from the project root.
load_dotenv()

POOL_CONFIG = {
    "minconn": int(os.getenv("DB_POOL_MIN", "1")),
    "maxconn": int(os.getenv("DB_POOL_MAX", "10")),
}

db_target = os.getenv("DB_TARGET", "local").lower()

if db_target == "render":
    render_url = os.getenv("RENDER_URL")
    if not render_url:
        raise RuntimeError("DB_TARGET is 'render' but RENDER_URL is not configured")
    PG_DB_CONFIG = {
        "dsn": render_url,
        "sslmode": "require",
        "options": "-c search_path=public",
    }
elif db_target == "local":
    PG_DB_CONFIG = {
        "host": os.getenv("LOCAL_HOST", "localhost"),
        "port": int(os.getenv("LOCAL_PORT", "5432")),
        "user": os.getenv("LOCAL_USER"),
        "password": os.getenv("LOCAL_PASSWORD"),
        "dbname": os.getenv("LOCAL_DB"),
        "options": "-c search_path=public",
    }