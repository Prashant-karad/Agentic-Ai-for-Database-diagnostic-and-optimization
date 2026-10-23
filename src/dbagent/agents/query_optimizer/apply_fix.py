"""Ask the DBA for approval, then apply an approved index to the MAIN database safely.

Safety rules:
  - Nothing is applied without an explicit "yes" from a human.
  - The index is built with CREATE INDEX CONCURRENTLY, so the table stays
    readable AND writable while the index is being built.
  - After building, we check Postgres marked the index as valid; a failed
    concurrent build leaves an invalid index, which we remove.
  - Every applied fix comes with its undo (rollback) statement.
"""

from collections.abc import Callable

from dbagent.agents.query_optimizer.fix_proposer import CREATE_INDEX_PATTERN, FixProposal
from dbagent.agents.query_optimizer.sandbox import SandboxResult, get_index_name
from dbagent.core.db import Database


class ApplyError(Exception):
    """Raised when an approved fix could not be applied correctly."""


INDEX_VALID_SQL = """
SELECT i.indisvalid AS is_valid
FROM pg_class c
JOIN pg_index i ON i.indexrelid = c.oid
WHERE c.relname = %s
"""


def to_concurrent_sql(fix_sql: str) -> str:
    """'CREATE INDEX name ON ...'  ->  'CREATE INDEX CONCURRENTLY IF NOT EXISTS name ON ...'"""
    cleaned = fix_sql.strip().rstrip(";").strip()
    match = CREATE_INDEX_PATTERN.match(cleaned)
    if not match:
        raise ApplyError("The fix is not a plain CREATE INDEX statement.")
    after_create_index = cleaned[len("CREATE INDEX"):].strip()
    if after_create_index.upper().startswith("IF NOT EXISTS"):
        after_create_index = after_create_index[len("IF NOT EXISTS"):].strip()
    return f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {after_create_index}"


def rollback_sql(fix_sql: str) -> str:
    """The statement that undoes the fix."""
    return f"DROP INDEX CONCURRENTLY IF EXISTS {get_index_name(fix_sql)}"


def format_approval_request(proposal: FixProposal, result: SandboxResult) -> str:
    """The summary the DBA reads before deciding."""
    return "\n".join([
        "The agent wants to apply this fix to the MAIN database:",
        f"  SQL:     {proposal.sql}",
        f"  Why:     {proposal.reason}",
        f"  Sandbox: {result.before_ms:.2f} ms -> {result.after_ms:.2f} ms ({result.speedup:.0f}x faster)",
        f"  Plan:    {result.plan_before}  ->  {result.plan_after}",
        f"  Undo:    {rollback_sql(proposal.sql)}",
    ])


def ask_for_approval(
    proposal: FixProposal,
    result: SandboxResult,
    ask: Callable[[str], str] = input,
) -> bool:
    """Show the summary and return True only if the DBA types 'yes' (or 'y')."""
    print(format_approval_request(proposal, result))
    answer = ask("\nApply this fix to the main database? (yes/no): ")
    return answer.strip().lower() in ("yes", "y")


def is_index_valid(db: Database, index_name: str) -> bool:
    """True if the index exists and Postgres marked it valid (usable)."""
    row = db.fetch_one(INDEX_VALID_SQL, (index_name,))
    return bool(row and row["is_valid"])


def apply_fix_to_main(main_db: Database, fix_sql: str) -> str:
    """Build the index on the main database without blocking writes. Returns the SQL that ran."""
    concurrent_sql = to_concurrent_sql(fix_sql)
    index_name = get_index_name(fix_sql)

    # CONCURRENTLY cannot run inside a transaction, so this needs autocommit.
    main_db.execute_autocommit(concurrent_sql)

    if not is_index_valid(main_db, index_name):
        main_db.execute_autocommit(rollback_sql(fix_sql))
        raise ApplyError(f"Index {index_name} was not built correctly and has been removed.")
    return concurrent_sql