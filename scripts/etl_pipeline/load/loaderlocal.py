import os

import psycopg2

from load.baseloader import BaseLoader


class LoaderLocal(BaseLoader):
    """Local Docker Postgres/PostGIS (LOCAL_* variables in .env)."""

    def _connect(self):
        e = os.environ
        return psycopg2.connect(
            host=e["LOCAL_HOST"],
            port=e["LOCAL_PORT"],
            user=e["LOCAL_USER"],
            password=e["LOCAL_PASSWORD"],
            dbname=e["LOCAL_DB"],
        )