import os

import psycopg2

from load.baseloader import BaseLoader


class LoaderLocal(BaseLoader):
    
    """This local loader class is for Docker and not for the actual DB in render."""
    """It's imperative to remember that user credential are on the .env file if credentials are not added or are incorrect, the connection will fail."""
    """Refer to .env.example for the correct format and links of the .env file."""
    def _connect(self):
        e = os.environ
        return psycopg2.connect(
            host=e["LOCAL_HOST"],
            port=e["LOCAL_PORT"],
            user=e["LOCAL_USER"],
            password=e["LOCAL_PASSWORD"],
            dbname=e["LOCAL_DB"],
        )