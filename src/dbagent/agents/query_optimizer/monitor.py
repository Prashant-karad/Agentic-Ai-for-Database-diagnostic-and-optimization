"""Run the slow-query detector continuously in the background.

Every `interval_s` seconds: take a pg_stat_statements snapshot, compare it with
the previous one, flag slow queries and update the learned baselines.
A flagged query becomes CONFIRMED after `config.confirm_after` windows in a row.
The UI (or any other code) reads the latest result with status().
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from dbagent.agents.query_optimizer.detector import (
    DetectorConfig,
    SlowQuery,
    confirmed_slow_queries,
    detect_slow_queries,
    update_baselines,
    update_streaks,
)
from dbagent.core.db import Database
from dbagent.telemetry.query_stats import QueryWindow, Snapshot, diff_snapshots, take_snapshot


@dataclass
class MonitorStatus:
    """The latest picture of query health."""

    checked_at: float = 0.0                       # time.time() of the last check (0 = never)
    windows: list[QueryWindow] = field(default_factory=list)
    slow_queries: list[SlowQuery] = field(default_factory=list)     # flagged this window
    confirmed: list[SlowQuery] = field(default_factory=list)        # flagged several windows in a row
    baselines_learned: int = 0
    error: str = ""


class LiveMonitor:
    """Background thread that keeps checking query health."""

    def __init__(
        self,
        db: Database,
        interval_s: float = 10.0,
        config: DetectorConfig = DetectorConfig(),
        snapshot_fn: Callable[[Database], Snapshot] = take_snapshot,
    ):
        self.db = db
        self.interval_s = interval_s
        self.config = config
        self._snapshot_fn = snapshot_fn
        self._baselines: dict[int, float] = {}
        self._streaks: dict[int, int] = {}
        self._previous: Snapshot | None = None
        self._status = MonitorStatus()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_once(self) -> MonitorStatus:
        """Do one check now (also used by the background loop)."""
        try:
            current = self._snapshot_fn(self.db)
        except Exception as error:  # keep the monitor alive if the database blips
            with self._lock:
                self._status.error = str(error)
            return self.status()

        if self._previous is None:
            self._previous = current
            return self.status()

        windows = diff_snapshots(self._previous, current)
        slow = detect_slow_queries(windows, self._baselines, self.config)
        flagged_ids = {s.window.queryid for s in slow}
        self._streaks = update_streaks(self._streaks, windows, flagged_ids, self.config.min_calls)
        confirmed = confirmed_slow_queries(slow, self._streaks, self.config)
        self._baselines = update_baselines(self._baselines, windows, flagged_ids, self.config.baseline_alpha)
        self._previous = current

        with self._lock:
            self._status = MonitorStatus(
                checked_at=time.time(),
                windows=windows,
                slow_queries=slow,
                confirmed=confirmed,
                baselines_learned=len(self._baselines),
            )
        return self.status()

    def status(self) -> MonitorStatus:
        with self._lock:
            return self._status

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def forget_baselines(self) -> None:
        """Start learning 'normal' again (e.g. after a reset)."""
        self._baselines = {}
        self._streaks = {}

    def _loop(self) -> None:
        self.check_once()
        while not self._stop.wait(self.interval_s):
            self.check_once()