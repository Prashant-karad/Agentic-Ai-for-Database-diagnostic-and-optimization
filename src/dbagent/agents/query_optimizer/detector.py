"""Decide which queries are slow, using simple, explainable rules.

Two rules:
  1. Absolute: the query is slow right now (average above a fixed limit).
  2. Regression: the query got much slower than its own normal (baseline).

No AI here on purpose: rules are fast, free, predictable and easy to test.
"""

from dataclasses import dataclass

from dbagent.telemetry.query_stats import QueryWindow


@dataclass(frozen=True)
class DetectorConfig:
    slow_threshold_ms: float = 50.0   # rule 1: average slower than this is "slow"
    min_calls: int = 3                # ignore queries that ran too few times (noise)
    regression_factor: float = 2.0    # rule 2: this many times slower than baseline
    min_regression_ms: float = 5.0    # ...and at least this slow (ignore 0.1 -> 0.3 ms)
    baseline_alpha: float = 0.2       # how fast the baseline follows new data (0..1)


@dataclass(frozen=True)
class SlowQuery:
    """A query the detector flagged, with the evidence why."""

    window: QueryWindow
    baseline_ms: float | None
    reasons: tuple[str, ...]


def detect_slow_queries(
    windows: list[QueryWindow],
    baselines: dict[int, float],
    config: DetectorConfig = DetectorConfig(),
) -> list[SlowQuery]:
    """Return the queries that break at least one rule, busiest first."""
    flagged = []
    for w in windows:
        if w.calls < config.min_calls:
            continue

        reasons = []
        if w.mean_time_ms >= config.slow_threshold_ms:
            reasons.append(
                f"average {w.mean_time_ms:.1f} ms is above the "
                f"{config.slow_threshold_ms:.0f} ms limit"
            )

        baseline = baselines.get(w.queryid)
        if (
            baseline is not None
            and w.mean_time_ms >= baseline * config.regression_factor
            and w.mean_time_ms >= config.min_regression_ms
        ):
            slowdown = w.mean_time_ms / baseline if baseline > 0 else float("inf")
            reasons.append(
                f"{slowdown:.1f}x slower than its normal {baseline:.2f} ms"
            )

        if reasons:
            flagged.append(SlowQuery(window=w, baseline_ms=baseline, reasons=tuple(reasons)))

    return flagged


def update_baselines(
    baselines: dict[int, float],
    windows: list[QueryWindow],
    flagged_ids: set[int],
    alpha: float = DetectorConfig.baseline_alpha,
) -> dict[int, float]:
    """Return new baselines (exponential moving average of each query's mean time).

    Flagged queries are NOT updated, so a slow period never becomes the new normal.
    """
    updated = dict(baselines)
    for w in windows:
        if w.queryid in flagged_ids:
            continue
        old = updated.get(w.queryid)
        if old is None:
            updated[w.queryid] = w.mean_time_ms
        else:
            updated[w.queryid] = alpha * w.mean_time_ms + (1 - alpha) * old
    return updated