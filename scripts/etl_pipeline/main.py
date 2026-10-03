from pathlib import Path

import tomllib
from extract.extractor import Extractor

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "config.toml"

def main():
    with CONFIG_PATH.open("rb") as config_file:
        config = tomllib.load(config_file)

    extractor = Extractor(config)
    dataframes = extractor.extract()

    for table_name, df in dataframes.items():
        print(f"Table: {table_name}, Rows: {len(df)}")
        
        
if __name__ == "__main__":
    main()
