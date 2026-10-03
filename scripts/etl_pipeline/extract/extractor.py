from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]

class Extractor:
    """Extract one DataFrame per `<table>.parquet` source file.

    `config` may be a mapping containing `parquets_path` or a path string.
    Relative paths are resolved from the project root, so invocation location
    does not affect which files are read.
    """
    def __init__(self, config: Any) -> None:
        self.config = config 

    def _source_path(self) -> Path:
        configured_path = self.config["parquets_path"]

        path = Path(configured_path).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    def extract(self) -> dict[str, Any]:
        """Return ``{table_name: pandas.DataFrame}`` for all Parquet files."""
        source_path = self._source_path()

        parquet_files = sorted(source_path.glob("*.parquet"))

        return {file_path.stem: pd.read_parquet(file_path) for file_path in parquet_files}
