"""Continuously detect slow queries on the main database.

Learns each query's normal speed (baseline) while things are healthy,
then flags queries that are slow or got much slower than normal.

Usage:
    python scripts/detect_slow_queries.py          # check every 10 seconds
    python scripts/detect_slow_queries.py 5        # check every 5 seconds
"""

import sys
import time

from dbagent.agents.query_optimizer.detector import (
    DetectorConfig,
    SlowQuery,
    detect_slow_queries,
    update_baselines,
)
from dbagent.core.config import load_settings
from dbagent.core.db import Database
from dbagent.telemetry.query_stats import diff_snapshots, take_snapshot


def shorten(sql: str, width: int = 70) -> str:
    one_line = " ".join(sql.split())
    return one_line if len(one_line) <= width else one_line[: width - 3] + "..."


def print_findings(flagged: list[SlowQuery], checked: int, baselines: dict[int, float]) -> None:
    clock = time.strftime("%H:%M:%S")
    if not flagged:
        print(f"[{clock}] OK - {checked} active queries, none slow "
              f"({len(baselines)} baselines learned)")
        return
    print(f"[{clock}] {len(flagged)} SLOW QUERY(S) DETECTED")
    for slow in flagged:
        w = slow.window
        print(f"  queryid {w.queryid}: {shorten(w.query)}")
        print(f"    {w.calls} calls, avg {w.mean_time_ms:.2f} ms")
        for reason in slow.reasons:
            print(f"    - {reason}")


def main() -> None:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    config = DetectorConfig()
    db = Database(load_settings().main_db_url, name="main")
    baselines: dict[int, float] = {}

    print(f"Checking every {interval}s (limit {config.slow_threshold_ms:.0f} ms, "
          f"regression {config.regression_factor}x). Ctrl+C to stop.")
    before = take_snapshot(db)
    try:
        while True:
            time.sleep(interval)
            after = take_snapshot(db)
            windows = diff_snapshots(before, after)

            flagged = detect_slow_queries(windows, baselines, config)
            print_findings(flagged, len(windows), baselines)

            flagged_ids = {s.window.queryid for s in flagged}
            baselines = update_baselines(baselines, windows, flagged_ids, config.baseline_alpha)
            before = after
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()