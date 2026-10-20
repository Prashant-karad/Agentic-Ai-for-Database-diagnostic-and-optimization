"""Explain one query and list the problems the plan analyzer finds.

Usage (put the query in SINGLE quotes, so bash leaves $1 alone):
    python scripts/investigate_query.py 'SELECT id FROM orders WHERE customer_id = $1 LIMIT 10'
"""

import sys

from dbagent.agents.query_optimizer.plan_analyzer import find_problems, get_tables, plan_to_text
from dbagent.core.config import load_settings
from dbagent.core.db import Database
from dbagent.telemetry.explain import UnsafeQueryError, get_plan
from dbagent.telemetry.tables import get_table_sizes


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    sql = sys.argv[1]
    db = Database(load_settings().main_db_url, name="main")

    try:
        plan = get_plan(db, sql)
    except UnsafeQueryError as error:
        print(f"Refused: {error}")
        sys.exit(1)

    print("Plan:")
    for line in plan_to_text(plan):
        print("  " + line)

    tables = get_tables(plan)
    table_sizes = get_table_sizes(db, tables)
    print("\nTable sizes:", {table: f"{rows:,}" for table, rows in table_sizes.items()})

    problems = find_problems(plan, table_sizes)
    print(f"\nProblems found ({len(problems)}):")
    if not problems:
        print("  none - the plan looks fine")
    for problem in problems:
        print(f"  [{problem.severity.upper()}] {problem.kind}: {problem.detail}")


if __name__ == "__main__":
    main()