"""Tests for the sandbox tester (pure logic + a mock sandbox database)."""

import pytest

from dbagent.agents.query_optimizer.sandbox import (
    SandboxError,
    fill_params,
    find_param_columns,
    get_index_name,
    judge_improvement,
    main_plan_step,
    to_sql_literal,
    try_fix_in_sandbox,
    uses_index,
)

QUERY = "SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2"
FIX_SQL = "CREATE INDEX idx_orders_customer_created ON orders (customer_id, created_at DESC)"


# ---------- placeholders ----------

def test_find_param_columns():
    assert find_param_columns(QUERY) == {1: "customer_id", 2: "LIMIT"}


@pytest.mark.parametrize(
    "value, expected",
    [(42, "42"), (9.5, "9.5"), ("Pune", "'Pune'"), ("O'Brien", "'O''Brien'"), (None, "NULL"), (True, "TRUE")],
)
def test_to_sql_literal(value, expected):
    assert to_sql_literal(value) == expected


def test_fill_params_replaces_placeholders():
    filled = fill_params(QUERY, {1: 4242, 2: 10})

    assert filled == "SELECT id FROM orders WHERE customer_id = 4242 ORDER BY created_at DESC LIMIT 10"


def test_fill_params_with_missing_value_raises():
    with pytest.raises(SandboxError):
        fill_params(QUERY, {1: 4242})


# ---------- measuring helpers ----------

def test_main_plan_step_finds_the_bottom_step():
    plan = {"Node Type": "Limit", "Plans": [
        {"Node Type": "Index Scan", "Index Name": "idx_x", "Relation Name": "orders"}]}

    assert main_plan_step(plan) == "Index Scan using idx_x"


@pytest.mark.parametrize(
    "before_ms, after_ms, expected_improved",
    [
        (100.0, 0.5, True),     # 200x faster
        (100.0, 80.0, True),    # exactly 20% faster
        (100.0, 90.0, False),   # only 10% faster: not worth an index
        (100.0, 140.0, False),  # slower!
        (0.06, 0.04, False),    # "33% faster" but saves only 0.02 ms
    ],
)
def test_judge_improvement(before_ms, after_ms, expected_improved):
    improved, speedup = judge_improvement(before_ms, after_ms, min_improvement=0.2)

    assert improved == expected_improved
    assert speedup == pytest.approx(before_ms / after_ms)


def test_uses_index_looks_at_every_step():
    plan = {"Node Type": "Bitmap Heap Scan", "Plans": [
        {"Node Type": "Bitmap Index Scan", "Index Name": "idx_x"}]}

    assert uses_index(plan, "idx_x") is True
    assert uses_index(plan, "idx_other") is False


def test_get_index_name():
    assert get_index_name(FIX_SQL) == "idx_orders_customer_created"


# ---------- whole flow with a mock sandbox ----------

class MockSandboxDatabase:
    """Pretends to be the sandbox: slow before the index exists, fast after."""

    def __init__(self, fail_on_create: bool = False, planner_uses_index: bool = True):
        self.index_exists = False
        self.fail_on_create = fail_on_create
        self.planner_uses_index = planner_uses_index
        self.executed: list[str] = []

    def execute(self, sql: str, params=None) -> None:
        self.executed.append(sql)
        if sql.startswith("CREATE INDEX"):
            if self.fail_on_create:
                raise RuntimeError("disk full")
            self.index_exists = True
        elif sql.startswith("DROP INDEX"):
            self.index_exists = False

    def fetch_one(self, sql: str, params=None) -> dict:
        if self.index_exists and self.planner_uses_index:
            plan = {"Node Type": "Index Scan", "Index Name": "idx_orders_customer_created"}
            ms = 0.5
        else:
            plan = {"Node Type": "Seq Scan", "Relation Name": "orders"}
            ms = 100.0
        return {"QUERY PLAN": [{"Plan": plan, "Execution Time": ms}]}


def test_try_fix_measures_before_and_after():
    sandbox = MockSandboxDatabase()

    result = try_fix_in_sandbox(sandbox, QUERY, FIX_SQL, [{1: 4242, 2: 10}], runs=3)

    assert result.before_ms == 100.0
    assert result.after_ms == 0.5
    assert result.index_used is True
    assert result.improved is True
    assert result.speedup == pytest.approx(200.0)
    assert result.plan_before == "Seq Scan on orders"
    assert result.plan_after == "Index Scan using idx_orders_customer_created"


def test_fix_is_rejected_when_postgres_ignores_the_new_index():
    sandbox = MockSandboxDatabase(planner_uses_index=False)

    result = try_fix_in_sandbox(sandbox, QUERY, FIX_SQL, [{1: 4242, 2: 10}], runs=1)

    assert result.index_used is False
    assert result.improved is False


def test_try_fix_always_removes_the_index_afterwards():
    sandbox = MockSandboxDatabase()

    try_fix_in_sandbox(sandbox, QUERY, FIX_SQL, [{1: 4242, 2: 10}], runs=1)

    assert sandbox.executed[-1] == "DROP INDEX IF EXISTS idx_orders_customer_created"
    assert sandbox.index_exists is False


def test_sandbox_is_cleaned_up_even_when_the_fix_fails():
    sandbox = MockSandboxDatabase(fail_on_create=True)

    with pytest.raises(RuntimeError):
        try_fix_in_sandbox(sandbox, QUERY, FIX_SQL, [{1: 4242, 2: 10}], runs=1)

    assert sandbox.executed[-1] == "DROP INDEX IF EXISTS idx_orders_customer_created"