import os
from graphlib import TopologicalSorter
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql
from psycopg2.extras import execute_values

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

FK_QUERY = (
    "SELECT c.relname, p.relname FROM pg_constraint k "
    "JOIN pg_class c ON c.oid = k.conrelid JOIN pg_class p ON p.oid = k.confrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE k.contype = 'f' AND n.nspname = %s"
)
COLS_QUERY = (  # column name, type, and SRID (only set for geometry columns)
    "SELECT c.column_name, c.udt_name, g.srid FROM information_schema.columns c "
    "LEFT JOIN geometry_columns g ON g.f_table_schema = c.table_schema "
    "AND g.f_table_name = c.table_name AND g.f_geometry_column = c.column_name "
    "WHERE c.table_schema = %s AND c.table_name = %s"
)


class BaseLoader:
    """Shared logic: load ``{table: DataFrame}`` into Postgres/PostGIS in FK order."""

    schema = "public"

    def _connect(self):
        raise NotImplementedError

    def load(self, dataframes: dict[str, pd.DataFrame]) -> dict[str, int]:
        results, conn = {}, self._connect()
        try:
            with conn, conn.cursor() as cur:  # one transaction: all or nothing
                for table in self._load_order(cur, list(dataframes)):
                    results[table] = self._load_table(cur, table, dataframes[table])
        finally:
            conn.close()
        return results

    def _load_order(self, cur, tables: list[str]) -> list[str]:
        """Parents before children, based on foreign keys in the database."""
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
        cols = [c for c in df.columns if c in info]
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
        rows = list(data.where(data.notna(), None).itertuples(index=False, name=None))
        template = sql.SQL("({})").format(sql.SQL(", ").join(holders))
        execute_values(cur, query, rows, template=template, page_size=5000)
        return len(rows)