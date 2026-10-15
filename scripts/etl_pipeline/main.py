import argparse
from pathlib import Path

from dotenv import load_dotenv
from extract.extractor import Extractor
from load.loaderDatabase import LoaderDatabase
from load.loaderlocal import LoaderLocal

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOADERS = {"local": LoaderLocal, "render": LoaderDatabase}


def main():
    parser = argparse.ArgumentParser(description="Car-Tracking ETL")
    parser.add_argument("--target", choices=LOADERS, default="local",
                        help="database to load into (default: local)")
    parser.add_argument("--init", action="store_true",
                        help="create tables from dataset/schemas/*.sql before loading")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")

    extractor = Extractor()
    dataframes = extractor.extract()

    for table_name, df in dataframes.items():
        print(f"Table: {table_name}, Rows: {len(df)}")

    print(f"\nLoading into {args.target} database...")
    schemas_dir = PROJECT_ROOT / "dataset" / "schemas" if args.init else None
    results = LOADERS[args.target]().load(dataframes, schemas_dir)

    for table_name, count in results.items():
        print(f"Loaded {table_name}: {count} rows")


if __name__ == "__main__":
    main()