"""Find a fix for a slow query and test it in the SANDBOX (main database is not changed).

Usage (SINGLE quotes, so bash leaves $1 alone):
    # let the LLM propose the fix:
    python scripts/try_fix.py 'SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2'

    # or test your own fix (no LLM needed):
    python scripts/try_fix.py 'SELECT ...' 'CREATE INDEX idx_test ON orders (customer_id)'
"""

import sys

from dbagent.agents.query_optimizer.fix_proposer import (
    InvalidProposalError,
    check_create_index_sql,
    propose_fix,
)
from dbagent.agents.query_optimizer.plan_analyzer import find_problems, get_tables, plan_to_text
from dbagent.agents.query_optimizer.sandbox import SandboxError, pick_sample_params, try_fix_in_sandbox
from dbagent.core.config import load_llm_settings, load_sandbox_db_url, load_settings
from dbagent.core.db import Database
from dbagent.core.llm import LLMClient, LLMError
from dbagent.telemetry.explain import UnsafeQueryError, get_plan
from dbagent.telemetry.tables import get_columns, get_indexes, get_table_sizes


def main() -> None:
    if len(sys.argv) not in (2, 3):
        print(__doc__)
        sys.exit(1)
    query = sys.argv[1]
    manual_fix = sys.argv[2] if len(sys.argv) == 3 else None

    main_db = Database(load_settings().main_db_url, name="main")
    sandbox_db = Database(load_sandbox_db_url(), name="sandbox")

    try:
        # 1. Investigate on the main database (read-only)
        plan = get_plan(main_db, query)
        tables = get_tables(plan)
        if len(tables) != 1:
            print(f"Only single-table queries are supported for now (found {tables}).")
            sys.exit(1)
        table = tables[0]
        problems = find_problems(plan, get_table_sizes(main_db, tables))
        columns = get_columns(main_db, tables)

        # 2. Get a fix: yours, or the LLM's
        if manual_fix:
            fix_sql = check_create_index_sql(manual_fix, allowed_tables=tables)
            print(f"Testing your fix: {fix_sql}")
        else:
            if not any(problem.severity == "high" for problem in problems):
                print("No high-severity problem found, nothing to fix.")
                return
            llm_settings = load_llm_settings()
            llm = LLMClient(llm_settings.base_url, llm_settings.api_key, llm_settings.model)
            proposal = propose_fix(llm, query, plan_to_text(plan), problems, columns, get_indexes(main_db, tables))
            if proposal.fix_type == "no_change":
                print(f"LLM suggests no change: {proposal.reason}")
                return
            fix_sql = proposal.sql
            print(f"LLM proposed: {fix_sql}")
            print(f"Reason:       {proposal.reason}")

        # 3. Measure in the sandbox
        column_names = [column.split()[0] for column in columns[table]]
        samples = pick_sample_params(sandbox_db, query, table, column_names)
        print(f"\nTesting in the sandbox with sample values {samples} ...")
        result = try_fix_in_sandbox(sandbox_db, query, fix_sql, samples)

    except (UnsafeQueryError, InvalidProposalError, LLMError, SandboxError) as error:
        print(f"Stopped: {error}")
        sys.exit(1)

    # 4. Report
    print("\nSandbox result:")
    print(f"  before: {result.before_ms:10.2f} ms   ({result.plan_before})")
    print(f"  after:  {result.after_ms:10.2f} ms   ({result.plan_after})")
    print(f"  speedup: {result.speedup:.0f}x")
    print(f"  new index used by Postgres: {'yes' if result.index_used else 'NO'}")
    verdict = "WORKS - worth applying" if result.improved else "does NOT help enough - do not apply"
    print(f"  verdict: {verdict}")


if __name__ == "__main__":
    main()