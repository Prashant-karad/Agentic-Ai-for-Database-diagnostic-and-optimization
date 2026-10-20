"""Watch which queries use the most database time, refreshed every few seconds.

Usage:
    python scripts/watch_queries.py          # every 10 seconds
    python scripts/watch_queries.py 5        # every 5 seconds
"""

import sys
import time

from dbagent.core.config import load_settings
from dbagent.core.db import Database
from dbagent.telemetry.query_stats import QueryWindow, diff_snapshots, take_snapshot


def shorten(sql: str, width: int = 70) -> str:
    """Squash whitespace and cut long SQL so it fits on one line."""
    one_line = " ".join(sql.split())
    if len(one_line) <= width:
        return one_line
    return one_line[: width - 3] + "..."


def print_report(windows: list[QueryWindow], interval: int) -> None:
    print(f"\n--- Top queries in the last {interval}s ---")
    if not windows:
        print("(no queries ran)")
        return
    print(f"{'calls':>6} {'avg ms':>9} {'total ms':>10} {'disk blks':>9}  query")
    for w in windows[:5]:
        print(
            f"{w.calls:>6} {w.mean_time_ms:>9.2f} {w.total_time_ms:>10.1f} "
            f"{w.blocks_read_from_disk:>9}  {shorten(w.query)}"
        )


def main() -> None:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    db = Database(load_settings().main_db_url, name="main")

    print(f"Watching every {interval}s. Press Ctrl+C to stop.")
    before = take_snapshot(db)
    try:
        while True:
            time.sleep(interval)
            after = take_snapshot(db)
            print_report(diff_snapshots(before, after), interval)
            before = after
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()