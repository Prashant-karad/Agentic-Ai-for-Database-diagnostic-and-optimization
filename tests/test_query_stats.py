"""Tests for dbagent.telemetry.query_stats (pure logic, no database needed)."""

from datetime import datetime, timezone

import pytest

from dbagent.telemetry.query_stats import QueryStat, Snapshot, diff_snapshots


def make_stat(queryid: int, calls: int, total_ms: float, blks_read: int = 0) -> QueryStat:
    return QueryStat(
        queryid=queryid,
        query=f"SELECT {queryid}",
        calls=calls,
        total_exec_time_ms=total_ms,
        rows=0,
        shared_blks_hit=0,
        shared_blks_read=blks_read,
    )


def make_snapshot(*stats: QueryStat) -> Snapshot:
    return Snapshot(taken_at=datetime.now(timezone.utc), stats={s.queryid: s for s in stats})


def test_mean_time_uses_only_calls_inside_the_window():
    # 100 old calls averaged 1 ms; 10 new calls took 500 ms in total -> 50 ms each
    before = make_snapshot(make_stat(1, calls=100, total_ms=100.0))
    after = make_snapshot(make_stat(1, calls=110, total_ms=600.0))

    [window] = diff_snapshots(before, after)

    assert window.calls == 10
    assert window.total_time_ms == pytest.approx(500.0)
    assert window.mean_time_ms == pytest.approx(50.0)


def test_query_first_seen_in_after_snapshot_counts_fully():
    before = make_snapshot()
    after = make_snapshot(make_stat(7, calls=4, total_ms=40.0))

    [window] = diff_snapshots(before, after)

    assert window.calls == 4
    assert window.mean_time_ms == pytest.approx(10.0)


def test_query_with_no_new_calls_is_skipped():
    before = make_snapshot(make_stat(1, calls=5, total_ms=50.0))
    after = make_snapshot(make_stat(1, calls=5, total_ms=50.0))

    assert diff_snapshots(before, after) == []


def test_stats_reset_is_treated_as_fresh_start():
    # counter went DOWN -> someone ran pg_stat_statements_reset()
    before = make_snapshot(make_stat(1, calls=1000, total_ms=9000.0))
    after = make_snapshot(make_stat(1, calls=3, total_ms=30.0))

    [window] = diff_snapshots(before, after)

    assert window.calls == 3
    assert window.mean_time_ms == pytest.approx(10.0)


def test_results_sorted_by_total_time_descending():
    before = make_snapshot()
    after = make_snapshot(
        make_stat(1, calls=1000, total_ms=500.0),  # fast but frequent
        make_stat(2, calls=5, total_ms=5000.0),    # slow
        make_stat(3, calls=10, total_ms=50.0),
    )

    windows = diff_snapshots(before, after)

    assert [w.queryid for w in windows] == [2, 1, 3]