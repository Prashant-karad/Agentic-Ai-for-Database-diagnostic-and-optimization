"""The three actions the Query Optimizer agent can take: investigate, propose, verify.

The agent (agent.py) decides WHEN to use each action. This file says HOW each
action is done, by calling the modules built in the earlier steps.
"""

from dataclasses import dataclass

from dbagent.agents.query_optimizer.fix_proposer import FixProposal, propose_fix
from dbagent.agents.query_optimizer.plan_analyzer import PlanProblem, find_problems, get_tables, plan_to_text
from dbagent.agents.query_optimizer.sandbox import SandboxError, SandboxResult, pick_sample_params, try_fix_in_sandbox
from dbagent.core.db import Database
from dbagent.core.llm import LLMClient
from dbagent.telemetry.explain import get_plan
from dbagent.telemetry.tables import get_columns, get_indexes, get_table_sizes


@dataclass(frozen=True)
class Investigation:
    """Everything learned about one slow query."""

    query: str
    table: str
    plan_text: list[str]
    problems: list[PlanProblem]
    columns: dict[str, list[str]]
    indexes: dict[str, list[str]]
    samples: list[dict[int, object]]


class QueryOptimizerTools:
    """Real tools: main database (read only), sandbox database, and the LLM."""

    def __init__(self, main_db: Database, sandbox_db: Database, llm: LLMClient):
        self.main_db = main_db
        self.sandbox_db = sandbox_db
        self.llm = llm

    def investigate(self, query: str) -> Investigation:
        """Read the plan and schema from the main DB; pick sample values from the sandbox."""
        plan = get_plan(self.main_db, query)
        tables = get_tables(plan)
        if len(tables) != 1:
            raise SandboxError(f"Only single-table queries are supported for now (found {tables}).")
        table = tables[0]
        columns = get_columns(self.main_db, tables)
        column_names = [column.split()[0] for column in columns[table]]
        return Investigation(
            query=query,
            table=table,
            plan_text=plan_to_text(plan),
            problems=find_problems(plan, get_table_sizes(self.main_db, tables)),
            columns=columns,
            indexes=get_indexes(self.main_db, tables),
            samples=pick_sample_params(self.sandbox_db, query, table, column_names),
        )

    def propose(self, investigation: Investigation, feedback: list[str]) -> FixProposal:
        """Ask the LLM for a fix, telling it which earlier attempts failed."""
        return propose_fix(
            self.llm,
            investigation.query,
            investigation.plan_text,
            investigation.problems,
            investigation.columns,
            investigation.indexes,
            feedback,
        )

    def verify(self, investigation: Investigation, fix_sql: str) -> SandboxResult:
        """Measure the fix in the sandbox."""
        return try_fix_in_sandbox(self.sandbox_db, investigation.query, fix_sql, investigation.samples)