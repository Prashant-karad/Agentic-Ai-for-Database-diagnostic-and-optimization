"""Plain-Python helpers behind the dashboard buttons.

No Streamlit in this file, so everything here can be tested with pytest.
app.py only draws the screen and calls these functions.
"""

import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from dbagent.agents.query_optimizer.apply_fix import ApplyError, apply_fix_to_main
from dbagent.agents.query_optimizer.detector import worst_query
from dbagent.agents.query_optimizer.monitor import LiveMonitor, MonitorStatus
from dbagent.agents.query_optimizer.report import build_report, save_report
from dbagent.agents.query_optimizer.sandbox import fill_params, main_plan_step, measure_query_ms
from dbagent.agents.query_optimizer.tools import QueryOptimizerTools
from dbagent.core.config import PROJECT_ROOT, load_llm_settings, load_sandbox_db_url, load_settings
from dbagent.core.db import Database
from dbagent.core.llm import LLMClient
from shopsim.database import ShopDatabase
from shopsim.settings import load_shop_db_url
from shopsim.stats import ActionSummary
from shopsim.traffic import TrafficGenerator

REPORTS_DIR = PROJECT_ROOT / "reports"


# ---------- latency history (for the chart) ----------

class LatencyHistory:
    """p95 of every shop action over time. Records at most once every `every_s` seconds."""

    def __init__(self, every_s: float = 2.0, keep: int = 300):
        self.every_s = every_s
        self._rows: deque = deque(maxlen=keep)
        self._last = 0.0
        self._lock = threading.Lock()

    def record(self, summaries: list[ActionSummary], now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            if not summaries or now - self._last < self.every_s:
                return
            self._last = now
            self._rows.append({"time": now, **{s.name: s.p95_ms for s in summaries}})

    def rows(self) -> list[dict]:
        with self._lock:
            return list(self._rows)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()
            self._last = 0.0


# ---------- everything the dashboard needs, created once ----------

@dataclass
class DashboardContext:
    traffic: TrafficGenerator
    monitor: LiveMonitor
    shop_db: ShopDatabase
    main_db: Database
    tools: QueryOptimizerTools
    history: LatencyHistory


def create_context(monitor_interval_s: float = 5.0) -> DashboardContext:
    """Connect to everything and start the background monitor."""
    # Read ALL settings first, so a missing one fails before any thread is started.
    main_url = load_settings().main_db_url
    sandbox_url = load_sandbox_db_url()
    shop_url = load_shop_db_url()
    llm_settings = load_llm_settings()

    main_db = Database(main_url, name="main")
    tools = QueryOptimizerTools(
        main_db=main_db,
        sandbox_db=Database(sandbox_url, name="sandbox"),
        llm=LLMClient(llm_settings.base_url, llm_settings.api_key, llm_settings.model),
    )
    monitor = LiveMonitor(main_db, interval_s=monitor_interval_s)
    monitor.start()

    return DashboardContext(
        traffic=TrafficGenerator(shop_url),
        monitor=monitor,
        shop_db=ShopDatabase(shop_url),
        main_db=main_db,
        tools=tools,
        history=LatencyHistory(),
    )


# ---------- the agent run ----------

def shorten(sql: str, width: int = 80) -> str:
    one_line = " ".join(sql.split())
    return one_line if len(one_line) <= width else one_line[: width - 3] + "..."


def pick_query_to_fix(status: MonitorStatus) -> str | None:
    """Confirmed slow queries first; if none, the ones still being watched. None if all is healthy."""
    worst = worst_query(status.confirmed) or worst_query(status.slow_queries)
    return worst.window.query if worst else None


@dataclass(frozen=True)
class FixOutcome:
    """What happened after the DBA decided."""

    decision: str                 # applied / rejected / apply_failed / not_applicable
    message: str
    report_path: Path
    production_ms: float | None = None


def measure_on_main(main_db: Database, state: dict) -> tuple[float, str]:
    """Median query time and plan step on the MAIN database, using the agent's sample values."""
    measurements = [
        measure_query_ms(main_db, fill_params(state["query"], values), runs=3)
        for values in state["investigation"].samples
    ]
    return statistics.median(ms for ms, _ in measurements), main_plan_step(measurements[0][1])


def finish_run(main_db: Database, state: dict, approved: bool, reports_dir: Path = REPORTS_DIR) -> FixOutcome:
    """Apply the fix if it was approved (and proven), then always write the report."""
    applied_sql = production_ms = production_plan = None

    if state["status"] != "fixed":
        decision = "not_applicable"
        message = f"Agent finished with status '{state['status']}'. Nothing to apply."
    elif not approved:
        decision = "rejected"
        message = "Rejected. The main database was not changed."
    else:
        try:
            applied_sql = apply_fix_to_main(main_db, state["proposal"].sql)
        except ApplyError as error:
            decision = "apply_failed"
            message = f"Apply failed: {error}"
        else:
            decision = "applied"
            production_ms, production_plan = measure_on_main(main_db, state)
            message = f"Applied. The query now takes {production_ms:.2f} ms on main ({production_plan})."

    report = build_report(state, decision, applied_sql, production_ms, production_plan)
    path = save_report(report, reports_dir)
    return FixOutcome(decision=decision, message=message, report_path=path, production_ms=production_ms)