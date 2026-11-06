import os

import psycopg2
from load.baseloader import BaseLoader


class LoaderDatabase(BaseLoader):
    """Connect to Render using the credentials in RENDER_URL, matching the API."""

    def _connect(self):
        render_url = os.getenv("RENDER_URL")
        if not render_url:
            raise RuntimeError("Render ETL requires RENDER_URL to be configured")
        return psycopg2.connect(
            dsn=render_url,
            sslmode="require",
        )