"""Tests for approval and applying a fix (mock database, no real changes)."""

import pytest

from dbagent.agents.query_optimizer.apply_fix import (
    ApplyError,
    apply_fix_to_main,
    ask_for_approval,
    rollback_sql,
    to_concurrent_sql,
)
from dbagent.agents.query_optimizer.fix_proposer import FixProposal
from dbagent.agents.query_optimizer.sandbox import SandboxResult

FIX_SQL = "CREATE INDEX idx_orders_customer_created ON orders (customer_id, created_at DESC)"
PROPOSAL = FixProposal(fix_type="create_index", sql=FIX_SQL, reason="Avoids the full scan.")
RESULT = SandboxResult(
    before_ms=70.0, after_ms=0.06, speedup=1166.0, index_used=True, improved=True,
    plan_before="Seq Scan on orders", plan_after="Index Scan using idx_orders_customer_created",
)


@pytest.mark.parametrize(
    "fix_sql",
    [FIX_SQL, FIX_SQL + ";", "CREATE INDEX IF NOT EXISTS idx_orders_customer_created ON orders (customer_id, created_at DESC)"],
)
def test_to_concurrent_sql(fix_sql):
    assert to_concurrent_sql(fix_sql) == (
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_orders_customer_created ON orders (customer_id, created_at DESC)"
    )


def test_rollback_sql():
    assert rollback_sql(FIX_SQL) == "DROP INDEX CONCURRENTLY IF EXISTS idx_orders_customer_created"


@pytest.mark.parametrize("answer, expected", [("yes", True), ("Y", True), (" yes ", True), ("no", False), ("", False), ("ok", False)])
def test_only_yes_counts_as_approval(answer, expected):
    assert ask_for_approval(PROPOSAL, RESULT, ask=lambda question: answer) is expected


class MockMainDatabase:
    """Stands in for the main database: records statements, reports index validity."""

    def __init__(self, index_becomes_valid: bool = True):
        self.index_becomes_valid = index_becomes_valid
        self.autocommit_statements: list[str] = []

    def execute_autocommit(self, sql: str, params=None) -> None:
        self.autocommit_statements.append(sql)

    def fetch_one(self, sql: str, params=None) -> dict:
        return {"is_valid": self.index_becomes_valid}


def test_apply_builds_index_concurrently():
    main_db = MockMainDatabase()

    applied = apply_fix_to_main(main_db, FIX_SQL)

    assert applied.startswith("CREATE INDEX CONCURRENTLY")
    assert main_db.autocommit_statements == [applied]


def test_invalid_index_is_removed_and_reported():
    main_db = MockMainDatabase(index_becomes_valid=False)

    with pytest.raises(ApplyError):
        apply_fix_to_main(main_db, FIX_SQL)

    assert main_db.autocommit_statements[-1] == rollback_sql(FIX_SQL)