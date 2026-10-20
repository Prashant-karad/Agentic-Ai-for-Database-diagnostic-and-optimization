"""Basic facts about tables, from PostgreSQL's own catalog."""

from dbagent.core.db import Database

TABLE_SIZES_SQL = """
SELECT c.relname AS table_name, c.reltuples::bigint AS row_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
  AND n.nspname = 'public'
  AND c.relname = ANY(%s)
"""


def get_table_sizes(db: Database, tables: list[str]) -> dict[str, int]:
    """Approximate row count per table (from the last ANALYZE; -1 if never analyzed)."""
    if not tables:
        return {}
    rows = db.fetch_all(TABLE_SIZES_SQL, (tables,))
    return {row["table_name"]: row["row_count"] for row in rows}