"""Collect how long each shop action took, as seen by the customer."""

import threading
from collections import deque
from dataclasses import dataclass


def percentile(values: list[float], percent: float) -> float:
    """Value below which `percent`% of the values fall (nearest-rank method). 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, round(percent / 100 * len(ordered)))
    return ordered[rank - 1]


@dataclass(frozen=True)
class ActionSummary:
    """Numbers for one action, over its recent requests."""

    name: str
    calls: int              # total since start
    errors: int             # total since start
    avg_ms: float           # over the recent window
    p95_ms: float           # over the recent window


class LatencyStats:
    """Thread-safe store of recent request times per action.

    Averages use only the most recent `window` requests per action, so the
    numbers react quickly when something gets slower or faster.
    """

    def __init__(self, window: int = 500):
        self._window = window
        self._lock = threading.Lock()
        self._recent: dict[str, deque] = {}
        self._calls: dict[str, int] = {}
        self._errors: dict[str, int] = {}

    def record(self, action: str, duration_ms: float, ok: bool = True) -> None:
        with self._lock:
            self._calls[action] = self._calls.get(action, 0) + 1
            if not ok:
                self._errors[action] = self._errors.get(action, 0) + 1
                return
            self._recent.setdefault(action, deque(maxlen=self._window)).append(duration_ms)

    def summary(self) -> list[ActionSummary]:
        """One summary per action, slowest (p95) first."""
        with self._lock:
            summaries = []
            for name, calls in self._calls.items():
                recent = list(self._recent.get(name, []))
                summaries.append(
                    ActionSummary(
                        name=name,
                        calls=calls,
                        errors=self._errors.get(name, 0),
                        avg_ms=sum(recent) / len(recent) if recent else 0.0,
                        p95_ms=percentile(recent, 95),
                    )
                )
        return sorted(summaries, key=lambda s: s.p95_ms, reverse=True)

    def reset(self) -> None:
        with self._lock:
            self._recent.clear()
            self._calls.clear()
            self._errors.clear()