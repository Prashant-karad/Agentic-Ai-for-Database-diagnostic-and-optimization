"""Test a proposed fix on the SANDBOX database and measure if it really helps.

Steps:
  1. Pick real sample values for the query's $1, $2 ... placeholders.
  2. Measure the query (EXPLAIN ANALYZE = really run it) BEFORE the fix.
  3. Apply the fix (CREATE INDEX) in the sandbox only.
  4. Measure again AFTER the fix.
  5. Always remove the fix again, so the sandbox stays clean.

Only the sandbox database is ever changed here - never the main database.
"""

import re
import statistics
from dataclasses import dataclass

from dbagent.agents.query_optimizer.fix_proposer import CREATE_INDEX_PATTERN
from dbagent.agents.query_optimizer.plan_analyzer import all_nodes
from dbagent.core.db import Database
from dbagent.telemetry.explain import check_select_only


class SandboxError(Exception):
    """Raised when the fix cannot be tested in the sandbox."""


@dataclass(frozen=True)
class SandboxResult:
    """What the sandbox measured for one fix."""

    before_ms: float               # median query time without the fix
    after_ms: float                # median query time with the fix
    speedup: float                 # before / after, e.g. 180.0 means 180x faster
    index_used: bool               # did the plan AFTER the fix really use the new index?
    improved: bool                 # True only if it is clearly faster AND the index is used
    plan_before: str               # main plan step before, e.g. "Seq Scan on orders"
    plan_after: str                # main plan step after, e.g. "Index Scan using idx_..."


# ---------- placeholders ($1, $2 ...) ----------

def find_param_columns(query: str) -> dict[int, str]:
    """Map each placeholder number to what it is compared with.

    'WHERE customer_id = $1 ... LIMIT $2'  ->  {1: 'customer_id', 2: 'LIMIT'}
    """
    params: dict[int, str] = {}
    for column, number in re.findall(r"(\w+)\s*(?:=|<|>|<=|>=)\s*\$(\d+)", query):
        params[int(number)] = column
    for number in re.findall(r"LIMIT\s+\$(\d+)", query, re.IGNORECASE):
        params[int(number)] = "LIMIT"
    return params


def to_sql_literal(value) -> str:
    """Write a Python value as SQL text: 42 -> 42, "Pune" -> 'Pune', None -> NULL."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def fill_params(query: str, values: dict[int, object]) -> str:
    """Replace $1, $2 ... with real values, so the query can actually run."""

    def replace(match: re.Match) -> str:
        number = int(match.group(1))
        if number not in values:
            raise SandboxError(f"No sample value for ${number}.")
        return to_sql_literal(values[number])

    return re.sub(r"\$(\d+)", replace, query)


def pick_sample_params(
    db: Database, query: str, table: str, table_columns: list[str], count: int = 3
) -> list[dict[int, object]]:
    """Pick real values from the table for each placeholder, e.g. [{1: 4242, 2: 10}, ...]."""
    param_columns = find_param_columns(query)
    numbers_in_query = {int(n) for n in re.findall(r"\$(\d+)", query)}
    missing = numbers_in_query - set(param_columns)
    if missing:
        raise SandboxError(f"Cannot work out sample values for: {sorted(missing)}")

    column_params = {n: col for n, col in param_columns.items() if col != "LIMIT"}
    for column in column_params.values():
        if column not in table_columns:
            raise SandboxError(f"Column '{column}' is not a column of '{table}'.")

    rows = []
    if column_params:
        # Names are checked against the real column list above, so building the SQL is safe.
        column_list = ", ".join(column_params.values())
        rows = db.fetch_all(f"SELECT {column_list} FROM {table} TABLESAMPLE SYSTEM (1) LIMIT %s", (count,))
        if not rows:
            raise SandboxError(f"Could not sample any rows from '{table}'.")

    samples = []
    for row in rows or [{}]:
        values: dict[int, object] = {n: row[col] for n, col in column_params.items()}
        for n, col in param_columns.items():
            if col == "LIMIT":
                values[n] = 10
        samples.append(values)
    return samples


# ---------- measuring ----------

def main_plan_step(plan: dict) -> str:
    """Short description of the step that reads the table, e.g. 'Index Scan using idx_x'."""
    node = plan
    while node.get("Plans"):
        node = node["Plans"][0]
    text = node["Node Type"]
    if "Index Name" in node:
        text += f" using {node['Index Name']}"
    elif "Relation Name" in node:
        text += f" on {node['Relation Name']}"
    return text


def uses_index(plan: dict, index_name: str) -> bool:
    """True if any step of the plan reads the given index."""
    return any(node.get("Index Name") == index_name for node in all_nodes(plan))


def measure_query_ms(db: Database, runnable_query: str, runs: int = 5) -> tuple[float, dict]:
    """Run the query `runs` times with EXPLAIN ANALYZE; return (median ms, plan of the last run)."""
    safe_query = check_select_only(runnable_query)
    times = []
    plan: dict = {}
    for run in range(runs + 1):
        row = db.fetch_one(f"EXPLAIN (ANALYZE, FORMAT JSON) {safe_query}")
        result = row["QUERY PLAN"][0]
        if run == 0:
            continue  # warm-up run: loads data into memory, not counted
        times.append(result["Execution Time"])
        plan = result["Plan"]
    return statistics.median(times), plan


def judge_improvement(
    before_ms: float,
    after_ms: float,
    min_improvement: float = 0.2,
    min_saved_ms: float = 1.0,
) -> tuple[bool, float]:
    """Is the fix clearly faster? Returns (improved, speedup).

    Needs BOTH: at least `min_improvement` (20%) faster, and at least
    `min_saved_ms` (1 ms) saved - 0.06 -> 0.04 ms is "33%" but worthless.
    """
    speedup = before_ms / after_ms if after_ms > 0 else float("inf")
    improved = (
        after_ms <= before_ms * (1 - min_improvement)
        and before_ms - after_ms >= min_saved_ms
    )
    return improved, speedup


# ---------- the whole test ----------

def get_index_name(fix_sql: str) -> str:
    """Index name from a CREATE INDEX statement."""
    match = CREATE_INDEX_PATTERN.match(fix_sql.strip().rstrip(";").strip())
    if not match:
        raise SandboxError("The fix is not a CREATE INDEX statement.")
    return match.group(1)


def try_fix_in_sandbox(
    sandbox_db: Database,
    query: str,
    fix_sql: str,
    param_sets: list[dict[int, object]],
    runs: int = 5,
    min_improvement: float = 0.2,
) -> SandboxResult:
    """Measure the query before and after applying fix_sql in the sandbox, then undo the fix."""
    index_name = get_index_name(fix_sql)
    runnable_queries = [fill_params(query, values) for values in param_sets]

    before = [measure_query_ms(sandbox_db, q, runs) for q in runnable_queries]

    sandbox_db.execute(f"DROP INDEX IF EXISTS {index_name}")
    try:
        sandbox_db.execute(fix_sql)
        after = [measure_query_ms(sandbox_db, q, runs) for q in runnable_queries]
    finally:
        sandbox_db.execute(f"DROP INDEX IF EXISTS {index_name}")  # always leave the sandbox clean

    before_ms = statistics.median(ms for ms, _ in before)
    after_ms = statistics.median(ms for ms, _ in after)
    faster, speedup = judge_improvement(before_ms, after_ms, min_improvement)
    index_used = all(uses_index(plan, index_name) for _, plan in after)
    return SandboxResult(
        before_ms=before_ms,
        after_ms=after_ms,
        speedup=speedup,
        index_used=index_used,
        improved=faster and index_used,
        plan_before=main_plan_step(before[0][1]),
        plan_after=main_plan_step(after[0][1]),
    )