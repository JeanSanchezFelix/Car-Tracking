import os

import psycopg2
from load.baseloader import BaseLoader

from backend.app.config.database import render_connection_config


class LoaderDatabase(BaseLoader):
    """Use the same Render URL and credential resolution as the API."""

    def _connect(self):
        return psycopg2.connect(**render_connection_config(os.environ))
