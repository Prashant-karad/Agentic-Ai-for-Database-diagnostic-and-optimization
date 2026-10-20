"""Ask the LLM to propose a fix for a slow query, then check the answer.

The LLM only SUGGESTS. Nothing here runs the suggested SQL. Every answer is
validated by code; the sandbox (next step) will measure whether it really helps.
"""

import re
from dataclasses import dataclass

from dbagent.agents.query_optimizer.plan_analyzer import PlanProblem
from dbagent.core.llm import LLMClient


class InvalidProposalError(ValueError):
    """Raised when the LLM's answer is not a safe, usable fix."""


@dataclass(frozen=True)
class FixProposal:
    """A fix suggested by the LLM, after validation."""

    fix_type: str          # "create_index" or "no_change"
    sql: str | None        # the CREATE INDEX statement (None for "no_change")
    reason: str            # the LLM's explanation, shown to the DBA


ALLOWED_FIX_TYPES = ("create_index", "no_change")

SYSTEM_PROMPT = """\
You are an expert PostgreSQL performance engineer.
You receive one slow query, its execution plan, the problems found in the plan,
and the tables' columns and existing indexes.

Your task: propose ONE fix.

Rules:
- The only fix you may propose is a single CREATE INDEX statement.
- Use only tables and columns that appear in the information given. Never invent names.
- Put columns used with "=" in WHERE first, then columns used in ORDER BY, in the same direction (ASC/DESC).
- Do not propose an index that already exists or that an existing index already covers.
- If no index would help, answer with fix_type "no_change".
- Do not use CONCURRENTLY.

Reply with ONLY a JSON object, no other text, in exactly this shape:
{"fix_type": "create_index" or "no_change",
 "sql": "CREATE INDEX ... ON ... (...)" or null,
 "reason": "one or two sentences explaining why this fix helps"}
"""

# CREATE INDEX [IF NOT EXISTS] name ON [public.]table [USING method] (columns...)
CREATE_INDEX_PATTERN = re.compile(
    r"^CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+"
    r"ON\s+(?:public\.)?(\w+)\s*"
    r"(?:USING\s+\w+\s*)?"
    r"\((.+)\)$",
    re.IGNORECASE | re.DOTALL,
)


def build_user_prompt(
    query: str,
    plan_text: list[str],
    problems: list[PlanProblem],
    columns: dict[str, list[str]],
    indexes: dict[str, list[str]],
) -> str:
    """Put all the evidence into one clear message for the LLM."""
    lines = ["Slow query:", query, "", "Execution plan:"]
    lines += plan_text
    lines += ["", "Problems found in the plan:"]
    lines += [f"- [{problem.severity}] {problem.detail}" for problem in problems] or ["- none"]
    lines += ["", "Tables:"]
    for table, table_columns in columns.items():
        lines.append(f"Table {table}: columns {', '.join(table_columns)}")
        existing = indexes.get(table, [])
        lines.append(f"  Existing indexes: {'; '.join(existing) if existing else 'none'}")
    return "\n".join(lines)


def check_create_index_sql(sql: str, allowed_tables: list[str]) -> str:
    """Return the cleaned SQL if it is one safe CREATE INDEX on a known table, else raise."""
    cleaned = sql.strip().rstrip(";").strip()
    if ";" in cleaned:
        raise InvalidProposalError("Only a single statement is allowed (found ';').")
    match = CREATE_INDEX_PATTERN.match(cleaned)
    if not match:
        raise InvalidProposalError(f"Not a plain CREATE INDEX statement: {cleaned[:120]!r}")
    table = match.group(2).lower()
    if table not in allowed_tables:
        raise InvalidProposalError(f"Index is on table '{table}', which is not part of this query.")
    return cleaned


def parse_proposal(data: dict, allowed_tables: list[str]) -> FixProposal:
    """Turn the LLM's JSON into a FixProposal, checking every field."""
    fix_type = data.get("fix_type")
    if fix_type not in ALLOWED_FIX_TYPES:
        raise InvalidProposalError(f"Unknown fix_type {fix_type!r}; expected one of {ALLOWED_FIX_TYPES}.")

    reason = data.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidProposalError("The answer has no 'reason'.")

    if fix_type == "no_change":
        return FixProposal(fix_type="no_change", sql=None, reason=reason.strip())

    sql = data.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise InvalidProposalError("fix_type is 'create_index' but 'sql' is missing.")
    safe_sql = check_create_index_sql(sql, allowed_tables)
    return FixProposal(fix_type="create_index", sql=safe_sql, reason=reason.strip())


def propose_fix(
    llm: LLMClient,
    query: str,
    plan_text: list[str],
    problems: list[PlanProblem],
    columns: dict[str, list[str]],
    indexes: dict[str, list[str]],
) -> FixProposal:
    """Ask the LLM for a fix and return it only if it passes validation."""
    user_prompt = build_user_prompt(query, plan_text, problems, columns, indexes)
    answer = llm.ask_json(SYSTEM_PROMPT, user_prompt)
    return parse_proposal(answer, allowed_tables=list(columns))