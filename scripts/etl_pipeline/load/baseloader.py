import os
from pathlib import Path
from graphlib import TopologicalSorter
import pandas as pd
import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values


FK_QUERY = ( #--- SQL query to find foreign keys (child table -> parent table) so tables can be loaded in the right order ---
    "SELECT c.relname, p.relname FROM pg_constraint k "
    "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_class p ON p.oid = k.confrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE k.contype = 'f' AND n.nspname = %s"
)
COLS_QUERY = ( # --- SQL query to get each column's name, type and SRID
    "SELECT c.column_name, c.udt_name, g.srid FROM information_schema.columns c "
    "LEFT JOIN geometry_columns g ON g.f_table_schema = c.table_schema "
    "AND g.f_table_name = c.table_name AND g.f_geometry_column = c.column_name "
    "WHERE c.table_schema = %s AND c.table_name = %s"
)

# --- Shared logic for both loaders loaderlocal and loaderDatabase. Loads {table: DataFrame} into Postgres/PostGIS in foreign key order ---
class BaseLoader:
    """Shared logic: load ``{table: DataFrame}`` into Postgres/PostGIS in FK order."""

    schema = "public"

    def _connect(self): # each loader has its own implementation on how they connect to the database, either local or render.
        raise NotImplementedError

    
    def load(self, dataframes: dict[str, pd.DataFrame], schemas_dir: Path | None = None) -> dict[str, int]:
        results, conn = {}, self._connect()
        try:
            with conn, conn.cursor() as cur:  # --- Everything runs in one transaction: if any table fails, nothing is saved. change this as needed ---
                
                if schemas_dir:
                    self._apply_schemas(cur, schemas_dir)
                    
                for table in self._load_order(cur, list(dataframes)):
                    results[table] = self._load_table(cur, table, dataframes[table])
        finally:
            conn.close()
        return results

    
    def _apply_schemas(self, cur, schemas_dir: Path) -> None: # --- Creates the tables from the schemas/*.sql files. Used with the --init flag ---
        
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        
        pending = {p: p.read_text(encoding="utf-8-sig") for p in sorted(schemas_dir.glob("*.sql"))}
        
        # --- A file can fail if it references a table that does not exist yet, so failed files are retried ---
        # --- If a full pass finishes without any file succeeding, something is really wrong (the world is ending) and it stops ---

        while pending:
            failed, last = {}, None
            
            for path, ddl in pending.items():
                cur.execute("SAVEPOINT s")
                try:
                    cur.execute(ddl)
                    cur.execute("RELEASE SAVEPOINT s")
                except psycopg2.Error as exc:
                    cur.execute("ROLLBACK TO SAVEPOINT s")
                    failed[path], last = ddl, exc
                    
            if len(failed) == len(pending):
                raise RuntimeError(f"Could not apply: {[p.name for p in failed]}") from last
            pending = failed
     # --- Returns the tables sorted so parent tables are loaded firt, the children can wait for the adults to come back from the job (this pun sucks, TODO get a better pun) ---
    def _load_order(self, cur, tables: list[str]) -> list[str]:

        cur.execute(FK_QUERY, (self.schema,))
        
        graph = {t: set() for t in tables}
        
        for child, parent in cur.fetchall():
            
            if child in graph and parent in graph and child != parent:
                graph[child].add(parent)
                
        return list(TopologicalSorter(graph).static_order())

    def _load_table(self, cur, table: str, df: pd.DataFrame) -> int:
        
        cur.execute(COLS_QUERY, (self.schema, table))
        
        info = {name: (udt, srid) for name, udt, srid in cur.fetchall()}
        
        if not info:
            raise RuntimeError(f"Table {self.schema}.{table} does not exist")
        
        cols = [c for c in df.columns if c in info]  # --- Only keep the parquet columns that also exist in the database table ---
        
        if df.empty or not cols:
            return 0

        holders = []
        for c in cols:
            udt, srid = info[c]
            
            if udt != "geometry":
                holders.append(sql.SQL("%s"))
                continue
            
            first = df[c].dropna()
            
            is_bytes = len(first) > 0 and isinstance(first.iloc[0], (bytes, bytearray, memoryview))
            
            raw = "ST_GeomFromWKB(%s)" if is_bytes else "(%s)::geometry"  # WKB vs WKT/hex
            holders.append(sql.SQL("ST_SetSRID({}, {})").format(sql.SQL(raw), sql.Literal(srid or 4326)))
            

        query = sql.SQL("INSERT INTO {}.{} ({}) VALUES %s ON CONFLICT DO NOTHING").format(
            sql.Identifier(self.schema), sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols))
        )
        
        data = df[cols].astype(object)
        
        rows = list(data.where(data.notna(), None).itertuples(index=False, name=None)) # --- Pandas empty values (NaN / NaT) are replaced with None so the database stores them as NULL THIS IS TO BE CHANGED THIS IMPLEMENTATION IS ONLY FOR NOW ---
        
        template = sql.SQL("({})").format(sql.SQL(", ").join(holders))
        
        execute_values(cur, query, rows, template=template, page_size=5000)
        
        return len(rows)