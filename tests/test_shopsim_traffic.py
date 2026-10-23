"""Tests for the simulated shop traffic (no database needed)."""

import random
from collections import Counter

import pytest

from shopsim.actions import ACTIONS, MODES, choose_action
from shopsim.stats import LatencyStats, percentile


# ---------- actions ----------

def test_every_action_has_a_weight_for_every_mode():
    for action in ACTIONS:
        assert set(action.weights) == set(MODES)


def test_same_seed_gives_same_sequence():
    rng_a, rng_b = random.Random(7), random.Random(7)

    assert [choose_action(rng_a).name for _ in range(50)] == [choose_action(rng_b).name for _ in range(50)]


def test_flash_sale_is_mostly_category_browsing():
    rng = random.Random(1)

    counts = Counter(choose_action(rng, "flash_sale").name for _ in range(5000))

    assert counts.most_common(1)[0][0] == "browse_category"


def test_normal_traffic_is_mostly_my_orders():
    rng = random.Random(1)

    counts = Counter(choose_action(rng, "normal").name for _ in range(5000))

    assert counts.most_common(1)[0][0] == "my_orders"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        choose_action(random.Random(1), "black_friday")


def test_params_match_the_number_of_placeholders():
    rng = random.Random(3)
    for action in ACTIONS:
        assert len(action.make_params(rng)) == action.sql.count("%s")


# ---------- stats ----------

@pytest.mark.parametrize(
    "values, percent, expected",
    [
        ([], 95, 0.0),
        ([5.0], 95, 5.0),
        (list(range(1, 101)), 95, 95),
        (list(range(1, 101)), 50, 50),
    ],
)
def test_percentile(values, percent, expected):
    assert percentile(values, percent) == expected


def test_summary_counts_calls_errors_and_averages():
    stats = LatencyStats()
    for ms in (1.0, 2.0, 3.0):
        stats.record("my_orders", ms)
    stats.record("my_orders", 999.0, ok=False)

    [summary] = stats.summary()

    assert summary.calls == 4
    assert summary.errors == 1
    assert summary.avg_ms == pytest.approx(2.0)     # failed request not counted in timing


def test_summary_uses_only_the_recent_window():
    stats = LatencyStats(window=3)
    for ms in (100.0, 100.0, 1.0, 1.0, 1.0):        # old slow requests, then fast ones
        stats.record("my_orders", ms)

    [summary] = stats.summary()

    assert summary.avg_ms == pytest.approx(1.0)


def test_summary_is_sorted_slowest_first():
    stats = LatencyStats()
    stats.record("fast", 0.1)
    stats.record("slow", 90.0)

    assert [s.name for s in stats.summary()] == ["slow", "fast"]