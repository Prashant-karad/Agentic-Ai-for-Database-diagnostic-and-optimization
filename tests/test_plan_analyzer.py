"""Tests for the plan analyzer, using plans copied from real EXPLAIN output."""

from dbagent.agents.query_optimizer.plan_analyzer import (
    all_nodes,
    find_problems,
    get_tables,
    plan_to_text,
)

TABLE_SIZES = {"orders": 2_000_000, "customers": 200_000, "products": 10_000}

# EXPLAIN (GENERIC_PLAN, FORMAT JSON)
# SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2
# (no index on customer_id; unused keys removed)
ORDERS_BY_CUSTOMER_NO_INDEX = {
    "Node Type": "Limit", "Plan Rows": 1, "Total Cost": 28083.87,
    "Plans": [{
        "Node Type": "Gather Merge", "Plan Rows": 10, "Total Cost": 28084.92,
        "Plans": [{
            "Node Type": "Sort", "Plan Rows": 5, "Total Cost": 27083.74,
            "Sort Key": ["created_at DESC"],
            "Plans": [{
                "Node Type": "Seq Scan", "Parallel Aware": True,
                "Relation Name": "orders", "Plan Rows": 5, "Total Cost": 27083.67,
                "Filter": "(customer_id = $1)",
            }],
        }],
    }],
}

# SELECT name FROM customers WHERE id = $1   (uses the primary key)
CUSTOMER_BY_ID = {
    "Node Type": "Index Scan", "Index Name": "customers_pkey",
    "Relation Name": "customers", "Plan Rows": 1, "Total Cost": 8.44,
    "Index Cond": "(id = $1)",
}

# SELECT count(*) FROM products WHERE category = 'books'   (small table)
PRODUCTS_BY_CATEGORY = {
    "Node Type": "Aggregate", "Plan Rows": 1, "Total Cost": 206.01,
    "Plans": [{
        "Node Type": "Seq Scan", "Relation Name": "products",
        "Plan Rows": 2000, "Total Cost": 201.0,
        "Filter": "(category = 'books'::text)",
    }],
}


def test_all_nodes_visits_every_node_top_down():
    types = [node["Node Type"] for node in all_nodes(ORDERS_BY_CUSTOMER_NO_INDEX)]

    assert types == ["Limit", "Gather Merge", "Sort", "Seq Scan"]


def test_get_tables():
    assert get_tables(ORDERS_BY_CUSTOMER_NO_INDEX) == ["orders"]


def test_full_scan_of_big_table_for_few_rows_is_reported():
    problems = find_problems(ORDERS_BY_CUSTOMER_NO_INDEX, TABLE_SIZES)
    [scan] = [p for p in problems if p.kind == "full_table_scan"]

    assert scan.severity == "high"
    assert scan.table == "orders"
    assert scan.filter == "(customer_id = $1)"


def test_sort_is_reported_as_info_with_its_key():
    problems = find_problems(ORDERS_BY_CUSTOMER_NO_INDEX, TABLE_SIZES)
    [sort] = [p for p in problems if p.kind == "sort"]

    assert sort.severity == "info"
    assert sort.sort_key == ("created_at DESC",)


def test_index_scan_has_no_problems():
    assert find_problems(CUSTOMER_BY_ID, TABLE_SIZES) == []


def test_seq_scan_on_small_table_is_ignored():
    assert find_problems(PRODUCTS_BY_CATEGORY, TABLE_SIZES) == []


def test_seq_scan_keeping_most_rows_is_ignored():
    # big table, but the query wants 40% of it: an index would not help
    plan = {
        "Node Type": "Seq Scan", "Relation Name": "orders",
        "Plan Rows": 800_000, "Total Cost": 40000.0, "Filter": "(status <> 'cancelled')",
    }

    assert find_problems(plan, TABLE_SIZES) == []


def test_unknown_table_size_is_treated_as_small():
    # without size information we do not claim a missing index; the sort hint stays
    kinds = [p.kind for p in find_problems(ORDERS_BY_CUSTOMER_NO_INDEX, table_sizes={})]

    assert kinds == ["sort"]


def test_plan_to_text_shows_tree_with_indentation():
    lines = plan_to_text(ORDERS_BY_CUSTOMER_NO_INDEX)

    assert lines[0].startswith("-> Limit")
    assert lines[3].startswith("      -> Parallel Seq Scan on orders")


def test_high_severity_problems_come_first():
    kinds = [p.kind for p in find_problems(ORDERS_BY_CUSTOMER_NO_INDEX, TABLE_SIZES)]

    assert kinds == ["full_table_scan", "sort"]