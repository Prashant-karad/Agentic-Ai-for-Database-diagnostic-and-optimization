"""Run the Query Optimizer agent (LangGraph) for one slow query.

The agent investigates, asks the LLM for a fix, tests it in the SANDBOX,
and retries with feedback if the fix does not help. The main database is
NOT changed (applying an approved fix comes in the next step).

Usage (SINGLE quotes, so bash leaves $1 alone):
    python scripts/run_agent.py 'SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2'
"""

import sys

from dbagent.agents.query_optimizer.agent import run_optimizer
from dbagent.agents.query_optimizer.tools import QueryOptimizerTools
from dbagent.core.config import load_llm_settings, load_sandbox_db_url, load_settings
from dbagent.core.db import Database
from dbagent.core.llm import LLMClient


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    query = sys.argv[1]

    llm_settings = load_llm_settings()
    tools = QueryOptimizerTools(
        main_db=Database(load_settings().main_db_url, name="main"),
        sandbox_db=Database(load_sandbox_db_url(), name="sandbox"),
        llm=LLMClient(llm_settings.base_url, llm_settings.api_key, llm_settings.model),
    )

    print(f"Running the agent for:\n  {query}\n")
    state = run_optimizer(tools, query, max_attempts=3)

    print("Agent trace:")
    for line in state["log"]:
        print(f"  - {line}")

    print(f"\nFinal status: {state['status'].upper()}")
    if state["status"] == "fixed":
        result = state["result"]
        print(f"  fix:     {state['proposal'].sql}")
        print(f"  reason:  {state['proposal'].reason}")
        print(f"  before:  {result.before_ms:.2f} ms ({result.plan_before})")
        print(f"  after:   {result.after_ms:.2f} ms ({result.plan_after})")
        print(f"  speedup: {result.speedup:.0f}x  (measured in the sandbox)")


if __name__ == "__main__":
    main()