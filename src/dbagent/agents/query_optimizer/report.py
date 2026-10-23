"""Write a Markdown report of one agent run, for the DBA and for the project record."""

from datetime import datetime
from pathlib import Path

from dbagent.agents.query_optimizer.apply_fix import rollback_sql


def build_report(
    state: dict,
    decision: str,
    applied_sql: str | None = None,
    production_ms: float | None = None,
    production_plan: str | None = None,
    now: datetime | None = None,
) -> str:
    """Turn the agent's final state and the DBA's decision into a Markdown report.

    decision: "applied", "rejected" or "not_applicable" (nothing to approve).
    """
    now = now or datetime.now()
    lines = [
        "# Query Optimizer report",
        "",
        f"- **Time:** {now:%Y-%m-%d %H:%M:%S}",
        f"- **Query:** `{state['query']}`",
        f"- **Agent status:** {state['status']}",
        f"- **DBA decision:** {decision}",
        "",
        "## What the agent did",
    ]
    lines += [f"{number}. {line}" for number, line in enumerate(state["log"], start=1)]

    if state["attempts"]:
        lines += ["", "## Fixes tried", "", "| # | SQL | Outcome |", "|---|---|---|"]
        for number, attempt in enumerate(state["attempts"], start=1):
            lines.append(f"| {number} | `{attempt['sql'] or '-'}` | {attempt['outcome']} |")

    result = state.get("result")
    if state["status"] == "fixed" and result is not None:
        lines += [
            "",
            "## Sandbox measurement",
            "",
            "| | Time | Plan |",
            "|---|---|---|",
            f"| Before | {result.before_ms:.2f} ms | {result.plan_before} |",
            f"| After | {result.after_ms:.2f} ms | {result.plan_after} |",
            "",
            f"**Speedup: {result.speedup:.0f}x**",
            "",
            f"**Reason (LLM):** {state['proposal'].reason}",
        ]

    if decision == "applied":
        lines += ["", "## Applied to the main database", "", f"- **SQL run:** `{applied_sql}`"]
        if production_ms is not None:
            lines.append(f"- **Query time on main after the fix:** {production_ms:.2f} ms ({production_plan})")
        lines.append(f"- **To undo:** `{rollback_sql(state['proposal'].sql)}`")

    return "\n".join(lines) + "\n"


def save_report(text: str, folder: Path, now: datetime | None = None) -> Path:
    """Save the report as reports/optimizer-YYYYmmdd-HHMMSS.md and return its path."""
    now = now or datetime.now()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"optimizer-{now:%Y%m%d-%H%M%S}.md"
    path.write_text(text, encoding="utf-8")
    return path