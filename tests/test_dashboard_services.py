"""Tests for the dashboard helpers (no Streamlit, no database)."""

from dbagent.agents.query_optimizer.detector import SlowQuery
from dbagent.agents.query_optimizer.monitor import MonitorStatus
from dbagent.telemetry.query_stats import QueryWindow
from dashboard.services import LatencyHistory, finish_run, pick_query_to_fix
from shopsim.stats import ActionSummary


def slow(queryid: int, query: str, total_ms: float) -> SlowQuery:
    window = QueryWindow(queryid=queryid, query=query, calls=10, total_time_ms=total_ms,
                         mean_time_ms=total_ms / 10, blocks_read_from_disk=0)
    return SlowQuery(window=window, baseline_ms=None, reasons=("slow",))


# ---------- pick_query_to_fix ----------

def test_confirmed_query_is_picked_before_watched_ones():
    confirmed = slow(1, "SELECT confirmed", total_ms=1000)
    watched = slow(2, "SELECT watched", total_ms=9000)
    status = MonitorStatus(slow_queries=[confirmed, watched], confirmed=[confirmed])

    assert pick_query_to_fix(status) == "SELECT confirmed"


def test_watched_query_is_picked_when_nothing_is_confirmed_yet():
    status = MonitorStatus(slow_queries=[slow(2, "SELECT watched", total_ms=900)])

    assert pick_query_to_fix(status) == "SELECT watched"


def test_nothing_to_fix_when_healthy():
    assert pick_query_to_fix(MonitorStatus()) is None


# ---------- LatencyHistory ----------

def summary(name: str, p95: float) -> ActionSummary:
    return ActionSummary(name=name, calls=1, errors=0, avg_ms=p95, p95_ms=p95)


def test_history_records_p95_per_action():
    history = LatencyHistory(every_s=2)

    history.record([summary("my_orders", 350.0), summary("product_page", 0.4)], now=100.0)

    assert history.rows() == [{"time": 100.0, "my_orders": 350.0, "product_page": 0.4}]


def test_history_records_at_most_once_per_interval():
    history = LatencyHistory(every_s=2)

    history.record([summary("my_orders", 1.0)], now=100.0)
    history.record([summary("my_orders", 2.0)], now=101.0)      # too soon: skipped
    history.record([summary("my_orders", 3.0)], now=102.5)

    assert [row["my_orders"] for row in history.rows()] == [1.0, 3.0]


def test_history_clear():
    history = LatencyHistory()
    history.record([summary("my_orders", 1.0)], now=100.0)

    history.clear()

    assert history.rows() == []


# ---------- finish_run (paths that never touch the database) ----------

def no_problem_state():
    return {"query": "SELECT 1", "status": "no_problem", "log": ["nothing to fix"], "attempts": [], "result": None}


def test_nothing_to_apply_writes_a_report(tmp_path):
    outcome = finish_run(main_db=None, state=no_problem_state(), approved=True, reports_dir=tmp_path)

    assert outcome.decision == "not_applicable"
    assert outcome.report_path.exists()


def test_rejected_fix_changes_nothing_and_writes_a_report(tmp_path):
    state = {**no_problem_state(), "status": "fixed", "proposal": None, "result": None}

    outcome = finish_run(main_db=None, state=state, approved=False, reports_dir=tmp_path)

    assert outcome.decision == "rejected"
    assert "DBA decision:** rejected" in outcome.report_path.read_text()