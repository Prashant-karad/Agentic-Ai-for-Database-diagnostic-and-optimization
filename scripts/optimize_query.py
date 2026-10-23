"""Full Query Optimizer: agent finds and tests a fix -> DBA approves -> applied to main -> report.

Usage:
    python scripts/optimize_query.py              # watch the database and pick the slowest query itself
    python scripts/optimize_query.py --watch 30   # same, but watch for 30 seconds
    python scripts/optimize_query.py 'SELECT ...' # fix this exact query (SINGLE quotes, so bash leaves $1 alone)

Automatic mode needs traffic running (e.g. scripts/generate_traffic.py in another terminal).
"""

import statistics
import sys
import time

from dbagent.agents.query_optimizer.agent import run_optimizer
from dbagent.agents.query_optimizer.apply_fix import ApplyError, apply_fix_to_main, ask_for_approval
from dbagent.agents.query_optimizer.detector import detect_slow_queries, worst_query
from dbagent.agents.query_optimizer.report import build_report, save_report
from dbagent.agents.query_optimizer.sandbox import fill_params, main_plan_step, measure_query_ms
from dbagent.agents.query_optimizer.tools import QueryOptimizerTools
from dbagent.core.config import PROJECT_ROOT, load_llm_settings, load_sandbox_db_url, load_settings
from dbagent.core.db import Database
from dbagent.core.llm import LLMClient
from dbagent.telemetry.query_stats import diff_snapshots, take_snapshot


def find_query_to_fix(db: Database, seconds: int) -> str | None:
    """Watch the database for a while and return the slow query costing the most time."""
    print(f"Watching the main database for {seconds}s to find the slowest query...")
    before = take_snapshot(db)
    time.sleep(seconds)
    after = take_snapshot(db)

    worst = worst_query(detect_slow_queries(diff_snapshots(before, after), baselines={}))
    if worst is None:
        return None
    w = worst.window
    print(f"Slowest query: {w.calls} calls, avg {w.mean_time_ms:.1f} ms, {w.total_time_ms / 1000:.1f} s in total")
    print(f"  {w.query}\n")
    return w.query


def read_arguments() -> tuple[str | None, int]:
    """Return (query or None for automatic mode, seconds to watch)."""
    args = sys.argv[1:]
    if not args:
        return None, 15
    if args[0] == "--watch" and len(args) == 2 and args[1].isdigit():
        return None, int(args[1])
    if len(args) == 1 and not args[0].startswith("--"):
        return args[0], 0
    print(__doc__)
    sys.exit(1)


def main() -> None:
    query, watch_seconds = read_arguments()
    main_db = Database(load_settings().main_db_url, name="main")

    if query is None:
        query = find_query_to_fix(main_db, watch_seconds)
        if query is None:
            print("No slow query found. Is traffic running? Nothing to fix.")
            return

    llm_settings = load_llm_settings()
    tools = QueryOptimizerTools(
        main_db=main_db,
        sandbox_db=Database(load_sandbox_db_url(), name="sandbox"),
        llm=LLMClient(llm_settings.base_url, llm_settings.api_key, llm_settings.model),
    )

    # 1. The agent investigates, proposes and verifies in the sandbox
    print("Running the agent...\n")
    state = run_optimizer(tools, query, max_attempts=3)
    for line in state["log"]:
        print(f"  - {line}")
    print(f"\nAgent status: {state['status'].upper()}\n")

    decision = "not_applicable"
    applied_sql = production_ms = production_plan = None

    # 2. Human approval (only when the sandbox proved a fix works)
    if state["status"] == "fixed":
        if ask_for_approval(state["proposal"], state["result"]):
            # 3. Apply to the main database, then measure there too
            try:
                applied_sql = apply_fix_to_main(main_db, state["proposal"].sql)
            except ApplyError as error:
                print(f"\nApply failed: {error}")
                decision = "apply_failed"
            else:
                decision = "applied"
                print(f"\nApplied: {applied_sql}")
                samples = state["investigation"].samples
                measurements = [measure_query_ms(main_db, fill_params(query, values), runs=3) for values in samples]
                production_ms = statistics.median(ms for ms, _ in measurements)
                production_plan = main_plan_step(measurements[0][1])
                print(f"Query time on main now: {production_ms:.2f} ms ({production_plan})")
        else:
            decision = "rejected"
            print("\nNot applied. The main database was not changed.")

    # 4. Report
    report = build_report(state, decision, applied_sql, production_ms, production_plan)
    path = save_report(report, PROJECT_ROOT / "reports")
    print(f"\nReport saved: {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()