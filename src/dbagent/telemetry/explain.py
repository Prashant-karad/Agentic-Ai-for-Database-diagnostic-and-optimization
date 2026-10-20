"""Ask PostgreSQL how it plans to run a query (EXPLAIN), as JSON.

We use EXPLAIN (GENERIC_PLAN) because queries from pg_stat_statements contain
placeholders like $1 instead of real values. GENERIC_PLAN (PostgreSQL 16+) can
plan such queries. It does NOT run the query - it only shows the plan with
*estimated* row counts.
"""

from dbagent.core.db import Database


class UnsafeQueryError(ValueError):
    """Raised when a query is not a single read-only SELECT."""


def check_select_only(sql: str) -> str:
    """Return the cleaned SQL, or raise if it is not one SELECT/WITH statement."""
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        raise UnsafeQueryError("Only a single statement is allowed (found ';').")
    first_word = cleaned.split(None, 1)[0].upper() if cleaned else ""
    if first_word not in ("SELECT", "WITH"):
        raise UnsafeQueryError(f"Only SELECT queries can be explained, got '{first_word}'.")
    return cleaned


def get_plan(db: Database, sql: str) -> dict:
    """Return the root plan node of EXPLAIN (GENERIC_PLAN, FORMAT JSON) for sql."""
    safe_sql = check_select_only(sql)
    # EXPLAIN cannot take the query itself as a %s parameter, so the SQL is
    # added as text. That is only acceptable because check_select_only()
    # ran first and the SQL comes from the database's own statistics.
    row = db.fetch_one(f"EXPLAIN (GENERIC_PLAN, FORMAT JSON) {safe_sql}")
    return row["QUERY PLAN"][0]["Plan"]