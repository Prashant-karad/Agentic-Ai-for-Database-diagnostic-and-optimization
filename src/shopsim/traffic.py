"""Simulated customers using the shop database at the same time.

Each simulated user runs in its own thread with its own database connection
and keeps doing shop actions until stopped.
"""

import random
import threading
import time

import psycopg

from shopsim.actions import MODES, choose_action
from shopsim.stats import ActionSummary, LatencyStats


class TrafficGenerator:
    """Start, resize and stop a group of simulated users."""

    def __init__(self, db_url: str, pause_ms: int = 50, seed: int | None = None):
        self.db_url = db_url
        self.pause_ms = pause_ms
        self.seed = seed
        self.mode = "normal"
        self.stats = LatencyStats()
        self._target_users = 0
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ---------- control ----------

    def start(self, users: int = 4) -> None:
        """Start (or resize) the traffic with this many users."""
        self._stop.clear()
        self.set_users(users)

    def set_users(self, users: int) -> None:
        """Change how many users are active. Extra threads stop by themselves."""
        with self._lock:
            self._target_users = max(0, users)
            self._threads = [t for t in self._threads if t.is_alive()]
            for user_number in range(len(self._threads), self._target_users):
                thread = threading.Thread(target=self._user_loop, args=(user_number,), daemon=True)
                thread.start()
                self._threads.append(thread)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Unknown traffic mode {mode!r}; expected one of {MODES}.")
        self.mode = mode

    def stop(self) -> None:
        """Stop all users and wait for them to finish."""
        self._stop.set()
        with self._lock:
            self._target_users = 0
            threads, self._threads = self._threads, []
        for thread in threads:
            thread.join(timeout=5)

    # ---------- status ----------

    @property
    def running_users(self) -> int:
        return sum(1 for t in self._threads if t.is_alive())

    @property
    def is_running(self) -> bool:
        return self.running_users > 0

    def summary(self) -> list[ActionSummary]:
        return self.stats.summary()

    # ---------- one simulated user ----------

    def _user_loop(self, user_number: int) -> None:
        rng = random.Random(None if self.seed is None else self.seed + user_number)
        conn = None
        while not self._stop.is_set() and user_number < self._target_users:
            action = choose_action(rng, self.mode)
            started = time.perf_counter()
            try:
                if conn is None or conn.closed:
                    conn = psycopg.connect(
                        self.db_url, autocommit=True, connect_timeout=5, application_name="shop-traffic"
                    )
                conn.execute(action.sql, action.make_params(rng))
                ok = True
            except psycopg.Error:
                ok = False
                if conn is not None:
                    conn.close()
                conn = None
                time.sleep(1)  # database trouble: wait a moment before retrying
            elapsed_ms = (time.perf_counter() - started) * 1000
            self.stats.record(action.name, elapsed_ms, ok)
            time.sleep(self.pause_ms / 1000)
        if conn is not None:
            conn.close()