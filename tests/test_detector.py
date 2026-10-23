"""Tests for the query optimizer's slow-query detector."""

import pytest

from dbagent.agents.query_optimizer.detector import (
    DetectorConfig,
    confirmed_slow_queries,
    detect_slow_queries,
    update_baselines,
    update_streaks,
    worst_query,
)
from dbagent.telemetry.query_stats import QueryWindow

CONFIG = DetectorConfig(
    slow_threshold_ms=50.0,
    min_calls=3,
    regression_factor=2.0,
    min_regression_ms=5.0,
    baseline_alpha=0.2,
    confirm_after=2,
)


def make_window(queryid: int, mean_ms: float, calls: int = 10) -> QueryWindow:
    return QueryWindow(
        queryid=queryid,
        query=f"SELECT {queryid}",
        calls=calls,
        total_time_ms=mean_ms * calls,
        mean_time_ms=mean_ms,
        blocks_read_from_disk=0,
    )


# ---------- detect_slow_queries ----------

def test_query_above_absolute_limit_is_flagged():
    [slow] = detect_slow_queries([make_window(1, mean_ms=98.0)], baselines={}, config=CONFIG)

    assert slow.window.queryid == 1
    assert "above the 50 ms limit" in slow.reasons[0]


def test_fast_query_is_not_flagged():
    assert detect_slow_queries([make_window(1, mean_ms=0.5)], baselines={1: 0.5}, config=CONFIG) == []


def test_query_with_too_few_calls_is_ignored():
    windows = [make_window(1, mean_ms=500.0, calls=2)]

    assert detect_slow_queries(windows, baselines={}, config=CONFIG) == []


def test_regression_against_baseline_is_flagged_even_below_absolute_limit():
    # normally 4 ms, now 20 ms: under the 50 ms limit, but 5x worse
    [slow] = detect_slow_queries([make_window(1, mean_ms=20.0)], baselines={1: 4.0}, config=CONFIG)

    assert slow.baseline_ms == 4.0
    assert "5.0x slower" in slow.reasons[0]


def test_tiny_regression_in_milliseconds_is_ignored():
    # 0.1 ms -> 0.4 ms is "4x" but nobody cares
    assert detect_slow_queries([make_window(1, mean_ms=0.4)], baselines={1: 0.1}, config=CONFIG) == []


def test_query_breaking_both_rules_gets_both_reasons():
    [slow] = detect_slow_queries([make_window(1, mean_ms=100.0)], baselines={1: 0.5}, config=CONFIG)

    assert len(slow.reasons) == 2


# ---------- update_baselines ----------

def test_new_query_baseline_starts_at_its_current_mean():
    baselines = update_baselines({}, [make_window(1, mean_ms=3.0)], flagged_ids=set(), alpha=0.2)

    assert baselines == {1: 3.0}


def test_baseline_moves_partly_towards_new_value():
    # 0.2 * 20 + 0.8 * 10 = 12
    baselines = update_baselines({1: 10.0}, [make_window(1, mean_ms=20.0)], flagged_ids=set(), alpha=0.2)

    assert baselines[1] == pytest.approx(12.0)


def test_flagged_query_does_not_change_its_baseline():
    baselines = update_baselines({1: 0.5}, [make_window(1, mean_ms=100.0)], flagged_ids={1}, alpha=0.2)

    assert baselines[1] == 0.5


def test_update_does_not_modify_the_input_dict():
    original = {1: 10.0}
    update_baselines(original, [make_window(1, mean_ms=20.0)], flagged_ids=set(), alpha=0.2)

    assert original == {1: 10.0}


# ---------- confirmation: slow several windows in a row ----------

def test_streak_grows_while_a_query_stays_flagged():
    streaks = {}
    for _ in range(3):
        streaks = update_streaks(streaks, [make_window(1, mean_ms=100)], flagged_ids={1})

    assert streaks[1] == 3


def test_streak_resets_when_the_query_is_fine_again():
    streaks = update_streaks({1: 2}, [make_window(1, mean_ms=1)], flagged_ids=set())

    assert streaks[1] == 0


def test_streak_kept_when_too_few_calls_to_judge():
    streaks = update_streaks({1: 1}, [make_window(1, mean_ms=1, calls=1)], flagged_ids=set(), min_calls=3)

    assert streaks[1] == 1


def test_one_noisy_window_is_not_confirmed():
    window = make_window(1, mean_ms=100)
    flagged = detect_slow_queries([window], {}, CONFIG)

    first = update_streaks({}, [window], {1})
    second = update_streaks(first, [window], {1})

    assert confirmed_slow_queries(flagged, first, CONFIG) == []
    assert len(confirmed_slow_queries(flagged, second, CONFIG)) == 1


def test_worst_query_is_the_one_costing_most_total_time():
    flagged = detect_slow_queries(
        [make_window(1, mean_ms=300, calls=2), make_window(2, mean_ms=60, calls=100)], {}, CONFIG
    )

    assert worst_query(flagged).window.queryid == 2       # 6000 ms in total beats 600 ms


def test_worst_query_of_nothing_is_none():
    assert worst_query([]) is None