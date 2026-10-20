"""Investigate one slow query and ask the LLM to propose a fix (nothing is executed).

Usage (SINGLE quotes, so bash leaves $1 alone):
    python scripts/propose_fix.py 'SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2'
"""

import sys

from dbagent.agents.query_optimizer.fix_proposer import InvalidProposalError, propose_fix
from dbagent.agents.query_optimizer.plan_analyzer import find_problems, get_tables, plan_to_text
from dbagent.core.config import load_llm_settings, load_settings
from dbagent.core.db import Database
from dbagent.core.llm import LLMClient, LLMError
from dbagent.telemetry.explain import UnsafeQueryError, get_plan
from dbagent.telemetry.tables import get_columns, get_indexes, get_table_sizes


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    query = sys.argv[1]

    db = Database(load_settings().main_db_url, name="main")
    llm_settings = load_llm_settings()
    llm = LLMClient(llm_settings.base_url, llm_settings.api_key, llm_settings.model)

    # 1. Investigate (same as investigate_query.py)
    try:
        plan = get_plan(db, query)
    except UnsafeQueryError as error:
        print(f"Refused: {error}")
        sys.exit(1)
    tables = get_tables(plan)
    problems = find_problems(plan, get_table_sizes(db, tables))
    plan_text = plan_to_text(plan)

    print("Problems found:")
    for problem in problems:
        print(f"  [{problem.severity.upper()}] {problem.detail}")
    if not any(problem.severity == "high" for problem in problems):
        print("\nNo high-severity problem, so the LLM is not asked.")
        return

    # 2. Ask the LLM, with the schema as context
    columns = get_columns(db, tables)
    indexes = get_indexes(db, tables)
    print(f"\nAsking {llm_settings.model} for a fix...")
    try:
        proposal = propose_fix(llm, query, plan_text, problems, columns, indexes)
    except (LLMError, InvalidProposalError) as error:
        print(f"No usable fix: {error}")
        sys.exit(1)

    # 3. Show the proposal (NOT executed - the sandbox step will test it)
    print("\nProposed fix (validated, not executed):")
    print(f"  type:   {proposal.fix_type}")
    print(f"  sql:    {proposal.sql}")
    print(f"  reason: {proposal.reason}")


if __name__ == "__main__":
    main()