import os
from pathlib import Path

from dotenv import load_dotenv

from backend.app.config.database import database_connection_config

# Resolve the development file independently of Uvicorn's working directory.
load_dotenv(Path(__file__).resolve().parents[3] / ".env")

POOL_CONFIG = {
    "minconn": int(os.getenv("DB_POOL_MIN", "1")),
    "maxconn": int(os.getenv("DB_POOL_MAX", "10")),
}

PG_DB_CONFIG = database_connection_config(os.environ)
