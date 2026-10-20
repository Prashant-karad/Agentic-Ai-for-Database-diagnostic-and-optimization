"""Tests for the EXPLAIN helper, using a fake database (no Postgres needed)."""

import pytest

from dbagent.telemetry.explain import UnsafeQueryError, check_select_only, get_plan


class FakeDatabase:
    """Pretends to be Database: records the SQL it receives, returns a canned row."""

    def __init__(self, row: dict):
        self.row = row
        self.received_sql: list[str] = []

    def fetch_one(self, sql: str, params=None) -> dict:
        self.received_sql.append(sql)
        return self.row


def test_get_plan_returns_root_plan_node():
    plan = {"Node Type": "Seq Scan", "Relation Name": "orders"}
    db = FakeDatabase(row={"QUERY PLAN": [{"Plan": plan}]})

    result = get_plan(db, "SELECT * FROM orders WHERE customer_id = $1")

    assert result == plan
    assert db.received_sql == [
        "EXPLAIN (GENERIC_PLAN, FORMAT JSON) SELECT * FROM orders WHERE customer_id = $1"
    ]


def test_trailing_semicolon_and_spaces_are_removed():
    assert check_select_only("  SELECT 1;  ") == "SELECT 1"


def test_with_query_is_allowed():
    assert check_select_only("WITH x AS (SELECT 1) SELECT * FROM x").startswith("WITH")


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "   ",
        "UPDATE orders SET total = 0",
    ],
)
def test_unsafe_queries_are_rejected_before_reaching_the_database(sql):
    db = FakeDatabase(row={})

    with pytest.raises(UnsafeQueryError):
        get_plan(db, sql)

    assert db.received_sql == []