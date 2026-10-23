"""Tests for the background monitor (mock snapshots, no database)."""

from datetime import datetime, timezone

from dbagent.agents.query_optimizer.detector import DetectorConfig
from dbagent.agents.query_optimizer.monitor import LiveMonitor
from dbagent.telemetry.query_stats import QueryStat, Snapshot


def snapshot(calls: int, total_ms: float) -> Snapshot:
    stat = QueryStat(queryid=1, query="SELECT 1", calls=calls, total_exec_time_ms=total_ms,
                     rows=0, shared_blks_hit=0, shared_blks_read=0)
    return Snapshot(taken_at=datetime.now(timezone.utc), stats={1: stat})


def test_monitor_learns_normal_then_flags_a_slowdown():
    snapshots = iter([
        snapshot(calls=0, total_ms=0),          # first check: just remembers
        snapshot(calls=10, total_ms=5),         # 0.5 ms per call -> normal, learned
        snapshot(calls=20, total_ms=1005),      # 100 ms per call -> slow
    ])
    monitor = LiveMonitor(db=None, snapshot_fn=lambda db: next(snapshots), config=DetectorConfig())

    monitor.check_once()
    healthy = monitor.check_once()
    slow = monitor.check_once()

    assert healthy.slow_queries == []
    assert healthy.baselines_learned == 1
    assert len(slow.slow_queries) == 1
    assert len(slow.slow_queries[0].reasons) == 2       # over the limit AND a regression


def test_monitor_survives_a_database_error():
    def broken(db):
        raise RuntimeError("connection refused")

    monitor = LiveMonitor(db=None, snapshot_fn=broken)

    status = monitor.check_once()

    assert "connection refused" in status.error


def test_monitor_confirms_only_after_two_slow_windows_in_a_row():
    snapshots = iter([
        snapshot(calls=0, total_ms=0),
        snapshot(calls=10, total_ms=1000),      # 100 ms per call -> flagged, watching (1/2)
        snapshot(calls=20, total_ms=2000),      # still 100 ms -> confirmed (2/2)
    ])
    monitor = LiveMonitor(db=None, snapshot_fn=lambda db: next(snapshots), config=DetectorConfig())

    monitor.check_once()
    first = monitor.check_once()
    second = monitor.check_once()

    assert len(first.slow_queries) == 1 and first.confirmed == []
    assert len(second.confirmed) == 1