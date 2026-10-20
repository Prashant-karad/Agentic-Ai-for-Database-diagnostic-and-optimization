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




COLUMNS_SQL = """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = ANY(%s)
ORDER BY table_name, ordinal_position
"""

INDEXES_SQL = """
SELECT tablename AS table_name, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = ANY(%s)
ORDER BY tablename, indexname
"""


def get_columns(db: Database, tables: list[str]) -> dict[str, list[str]]:
    """Columns of each table, as 'name type' strings, e.g. {'orders': ['id integer', ...]}."""
    if not tables:
        return {}
    columns: dict[str, list[str]] = {}
    for row in db.fetch_all(COLUMNS_SQL, (tables,)):
        columns.setdefault(row["table_name"], []).append(f"{row['column_name']} {row['data_type']}")
    return columns


def get_indexes(db: Database, tables: list[str]) -> dict[str, list[str]]:
    """Existing indexes of each table, as their CREATE INDEX definitions."""
    if not tables:
        return {}
    indexes: dict[str, list[str]] = {}
    for row in db.fetch_all(INDEXES_SQL, (tables,)):
        indexes.setdefault(row["table_name"], []).append(row["indexdef"])
    return indexes