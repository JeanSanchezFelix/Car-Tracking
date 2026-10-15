import os

import psycopg2

from load.baseloader import BaseLoader


class LoaderDatabase(BaseLoader):
    """This class is for connecting to the Render DB and not the local one in Docker."""
    """It's imperative to remember that user credential are on the .env file if credentials are not added or are incorrect, the connection will fail."""
    """Refer to .env.example for the correct format of the .env file."""

    def _connect(self):
        e = os.environ
        return psycopg2.connect(
            e["RENDER_URL"],
            user=e["RENDER_USER"],
            password=e["RENDER_PASSWORD"],
            sslmode="require",
        )