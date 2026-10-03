import os

import psycopg2

from load.baseloader import BaseLoader


class LoaderDatabase(BaseLoader):
    """Render Postgres (RENDER_* variables in .env)."""

    def _connect(self):
        e = os.environ
        return psycopg2.connect(
            e["RENDER_URL"],
            user=e["RENDER_USER"],
            password=e["RENDER_PASSWORD"],
            sslmode="require",
        )