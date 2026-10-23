"""Dashboard: run the shop, break it, and watch the agent find and fix the problem.

Run (from the project folder):
    streamlit run src/dashboard/app.py --server.headless true
"""

import time
from dataclasses import asdict

import pandas as pd
import streamlit as st

from dashboard.services import (
    DashboardContext,
    LatencyHistory,
    create_context,
    finish_run,
    pick_query_to_fix,
    shorten,
)
from dbagent.agents.query_optimizer.agent import run_optimizer
from dbagent.agents.query_optimizer.apply_fix import format_approval_request
from dbagent.agents.query_optimizer.monitor import MonitorStatus
from dbagent.core.config import PROJECT_ROOT
from shopsim import scenarios
from shopsim.actions import MODES
from shopsim.stats import ActionSummary

st.set_page_config(page_title="DB Agent", page_icon="🛠️", layout="wide")


@st.cache_resource
def get_context() -> DashboardContext:
    """Created ONCE per server and shared by every browser tab, so traffic and monitor keep running."""
    return create_context()


# ---------- sidebar: traffic and scenarios ----------

def reset_everything(ctx: DashboardContext) -> str:
    message = scenarios.reset(ctx.shop_db, ctx.traffic)
    ctx.monitor.forget_baselines()
    ctx.history.clear()
    st.session_state.pop("run", None)
    return message


def sidebar(ctx: DashboardContext) -> None:
    st.sidebar.header("Shop traffic")
    users = st.sidebar.slider("Simulated users", min_value=1, max_value=40, value=4)
    mode = st.sidebar.selectbox("Traffic mode", MODES)
    start_col, stop_col = st.sidebar.columns(2)
    if start_col.button("Start / update"):
        ctx.traffic.set_mode(mode)
        ctx.traffic.start(users)
        st.toast(f"Traffic: {users} users, {mode}")
    if stop_col.button("Stop"):
        ctx.traffic.stop()
        st.toast("Traffic stopped")

    st.sidebar.header("Scenarios")
    actions = {
        "Make healthy": lambda: scenarios.make_healthy(ctx.shop_db),
        "Drop indexes (break it)": lambda: scenarios.drop_indexes(ctx.shop_db),
        "Start flash sale": lambda: scenarios.start_flash_sale(ctx.traffic),
        "End flash sale": lambda: scenarios.end_flash_sale(ctx.traffic),
        "Reset everything": lambda: reset_everything(ctx),
    }
    for label, action in actions.items():
        if st.sidebar.button(label):
            st.toast(action())


# ---------- live panels (refresh every 2 seconds) ----------

def latency_chart(history: LatencyHistory) -> None:
    rows = history.rows()
    if len(rows) < 2:
        st.caption("The chart appears after a few seconds of traffic.")
        return
    frame = pd.DataFrame(rows)
    frame["seconds ago"] = (frame["time"] - time.time()).round()
    st.line_chart(frame.drop(columns="time").set_index("seconds ago"), y_label="p95 ms")


def customer_panel(ctx: DashboardContext, summaries: list[ActionSummary]) -> None:
    st.subheader("What customers feel")
    users_col, mode_col = st.columns(2)
    users_col.metric("Users", ctx.traffic.running_users)
    mode_col.metric("Mode", ctx.traffic.mode)
    if not summaries:
        st.info("No traffic yet. Start it from the sidebar.")
        return
    st.dataframe(
        pd.DataFrame([asdict(s) for s in summaries]).round(2),
        hide_index=True,
        column_config={"name": "action", "avg_ms": "avg ms", "p95_ms": "p95 ms"},
    )
    latency_chart(ctx.history)


def health_panel(status: MonitorStatus) -> None:
    st.subheader("Database health (what the agent sees)")
    if status.error:
        st.error(f"Monitor cannot read the database: {status.error}")
    if status.checked_at == 0:
        st.info("Monitor is starting: it needs two snapshots to compare.")
        return

    confirmed_ids = {s.window.queryid for s in status.confirmed}
    for slow in status.confirmed:
        st.error(f"🔴 SLOW: `{shorten(slow.window.query)}`  \n" + "; ".join(slow.reasons))
    for slow in status.slow_queries:
        if slow.window.queryid not in confirmed_ids:
            st.warning(f"🟡 Watching: `{shorten(slow.window.query)}`  \n" + "; ".join(slow.reasons))
    if not status.slow_queries:
        st.success("🟢 All queries healthy")

    seconds_ago = time.time() - status.checked_at
    st.caption(f"Checked {seconds_ago:.0f}s ago · {status.baselines_learned} baselines learned")
    if status.windows:
        busiest = [
            {"query": shorten(w.query, 60), "calls": w.calls, "avg ms": round(w.mean_time_ms, 2)}
            for w in status.windows[:5]
        ]
        st.dataframe(pd.DataFrame(busiest), hide_index=True)


@st.fragment(run_every=2)
def live_panels(ctx: DashboardContext) -> None:
    summaries = ctx.traffic.summary()
    ctx.history.record(summaries)
    left, right = st.columns(2)
    with left:
        customer_panel(ctx, summaries)
    with right:
        health_panel(ctx.monitor.status())


# ---------- the agent ----------

def start_agent_run(ctx: DashboardContext) -> None:
    query = pick_query_to_fix(ctx.monitor.status())
    if query is None:
        st.info("No slow query right now. Start traffic and break something first.")
        return
    with st.status("The agent is working: investigate → propose → verify in sandbox...", expanded=True) as box:
        st.code(query, language="sql")
        state = run_optimizer(ctx.tools, query, max_attempts=3)
        box.update(label=f"Agent finished: {state['status'].upper()}", state="complete")
    st.session_state.run = {"state": state, "outcome": None}
    st.rerun()


def show_approval(ctx: DashboardContext, run: dict) -> None:
    state = run["state"]
    result = state["result"]
    st.markdown("#### The agent proposes a fix. Approve it?")
    before_col, after_col, speed_col = st.columns(3)
    before_col.metric("Sandbox before", f"{result.before_ms:.2f} ms")
    after_col.metric("Sandbox after", f"{result.after_ms:.2f} ms")
    speed_col.metric("Faster", f"{result.speedup:.0f}x")
    st.code(format_approval_request(state["proposal"], result), language="text")

    approve_col, reject_col = st.columns(2)
    if approve_col.button("✅ Approve and apply to main", type="primary"):
        with st.spinner("Building the index on main (CONCURRENTLY, the shop keeps running)..."):
            run["outcome"] = finish_run(ctx.main_db, state, approved=True)
        st.rerun()
    if reject_col.button("❌ Reject"):
        run["outcome"] = finish_run(ctx.main_db, state, approved=False)
        st.rerun()


def show_outcome(run: dict) -> None:
    outcome = run["outcome"]
    if outcome.decision == "applied":
        st.success(outcome.message)
    else:
        st.warning(outcome.message)
    st.caption(f"Report saved: {outcome.report_path.relative_to(PROJECT_ROOT)}")
    with st.expander("Show the report"):
        st.markdown(outcome.report_path.read_text(encoding="utf-8"))
    if st.button("Start a new run"):
        st.session_state.pop("run", None)
        st.rerun()


def agent_panel(ctx: DashboardContext) -> None:
    st.subheader("Query Optimizer agent")
    run = st.session_state.get("run")
    if run is None:
        if st.button("🔍 Find and fix the slowest query", type="primary"):
            start_agent_run(ctx)
        return

    state = run["state"]
    with st.expander(f"Agent trace: {state['status'].upper()}", expanded=True):
        st.code(state["query"], language="sql")
        for line in state["log"]:
            st.write(f"- {line}")

    if run["outcome"] is not None:
        show_outcome(run)
    elif state["status"] == "fixed":
        show_approval(ctx, run)
    else:
        run["outcome"] = finish_run(ctx.main_db, state, approved=False)  # nothing to approve
        st.rerun()


# ---------- page ----------

def main() -> None:
    st.title("🛠️ Agentic DB Optimizer")
    st.caption("The simulated shop on the left · the agent's view on the right · the agent below")
    try:
        ctx = get_context()
    except Exception as error:  # databases down, .env missing, ...
        st.error(f"Could not start: {error}")
        st.info("Check that the databases are running (bash scripts/start.sh) and .env is filled in.")
        st.stop()

    sidebar(ctx)
    live_panels(ctx)
    st.divider()
    agent_panel(ctx)


main()