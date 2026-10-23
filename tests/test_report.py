"""Tests for the Markdown report."""

from datetime import datetime

from dbagent.agents.query_optimizer.fix_proposer import FixProposal
from dbagent.agents.query_optimizer.report import build_report, save_report
from dbagent.agents.query_optimizer.sandbox import SandboxResult

FIX_SQL = "CREATE INDEX idx_orders_customer_created ON orders (customer_id, created_at DESC)"
NOW = datetime(2026, 10, 23, 14, 30, 0)


def make_fixed_state():
    return {
        "query": "SELECT id FROM orders WHERE customer_id = $1 LIMIT $2",
        "status": "fixed",
        "log": ["investigate: 2 problem(s), 1 high", f"propose #1: {FIX_SQL}", "verify: worked"],
        "attempts": [{"sql": FIX_SQL, "reason": "r", "outcome": "worked: 70.00 ms -> 0.06 ms (1166x)"}],
        "proposal": FixProposal(fix_type="create_index", sql=FIX_SQL, reason="Avoids the full scan."),
        "result": SandboxResult(
            before_ms=70.0, after_ms=0.06, speedup=1166.0, index_used=True, improved=True,
            plan_before="Seq Scan on orders", plan_after="Index Scan using idx_orders_customer_created",
        ),
    }


def test_report_for_applied_fix_has_measurements_and_undo():
    report = build_report(make_fixed_state(), "applied", applied_sql="CREATE INDEX CONCURRENTLY ...",
                          production_ms=0.05, production_plan="Index Scan using idx_orders_customer_created", now=NOW)

    assert "2026-10-23 14:30:00" in report
    assert "| Before | 70.00 ms | Seq Scan on orders |" in report
    assert "Speedup: 1166x" in report
    assert "Query time on main after the fix:** 0.05 ms" in report
    assert "DROP INDEX CONCURRENTLY IF EXISTS idx_orders_customer_created" in report


def test_report_for_rejected_fix_has_no_applied_section():
    report = build_report(make_fixed_state(), "rejected", now=NOW)

    assert "DBA decision:** rejected" in report
    assert "Applied to the main database" not in report


def test_report_when_nothing_was_wrong():
    state = {"query": "SELECT 1", "status": "no_problem", "log": ["nothing to fix"], "attempts": [], "result": None}

    report = build_report(state, "not_applicable", now=NOW)

    assert "Agent status:** no_problem" in report
    assert "Sandbox measurement" not in report


def test_save_report_writes_a_timestamped_file(tmp_path):
    path = save_report("# hi\n", tmp_path / "reports", now=NOW)

    assert path.name == "optimizer-20261023-143000.md"
    assert path.read_text() == "# hi\n"