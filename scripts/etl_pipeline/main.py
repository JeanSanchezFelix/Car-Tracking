from pathlib import Path

from dotenv import load_dotenv
from extract.extractor import Extractor

PROJECT_ROOT = Path(__file__).resolve().parents[2]

def main():
    load_dotenv(PROJECT_ROOT / ".env")

    extractor = Extractor()
    dataframes = extractor.extract()

    for table_name, df in dataframes.items():
        print(f"Table: {table_name}, Rows: {len(df)}")
        
if __name__ == "__main__":
    main()
