"""Tests for the fix proposer, using a fake LLM (no API key needed)."""

import pytest

from dbagent.agents.query_optimizer.fix_proposer import (
    InvalidProposalError,
    build_user_prompt,
    check_create_index_sql,
    parse_proposal,
    propose_fix,
)
from dbagent.agents.query_optimizer.plan_analyzer import PlanProblem
from dbagent.core.llm import extract_json

QUERY = "SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2"
PLAN_TEXT = ["-> Limit", "  -> Sort", "    -> Parallel Seq Scan on orders"]
PROBLEMS = [
    PlanProblem(
        kind="full_table_scan", severity="high", table="orders",
        filter="(customer_id = $1)", detail="Reads all ~2,000,000 rows of 'orders' to keep about 5",
    )
]
COLUMNS = {"orders": ["id integer", "customer_id integer", "created_at timestamp with time zone"]}
INDEXES = {"orders": ["CREATE UNIQUE INDEX orders_pkey ON public.orders USING btree (id)"]}
GOOD_SQL = "CREATE INDEX idx_orders_customer_created ON orders (customer_id, created_at DESC)"


class FakeLLM:
    """Pretends to be LLMClient: returns a prepared answer and records the prompts."""

    def __init__(self, answer_text: str):
        self.answer_text = answer_text
        self.prompts: list[tuple[str, str]] = []

    def ask_json(self, system_prompt: str, user_prompt: str) -> dict:
        self.prompts.append((system_prompt, user_prompt))
        return extract_json(self.answer_text)


# ---------- build_user_prompt ----------

def test_prompt_contains_all_the_evidence():
    prompt = build_user_prompt(QUERY, PLAN_TEXT, PROBLEMS, COLUMNS, INDEXES)

    assert QUERY in prompt
    assert "Parallel Seq Scan on orders" in prompt
    assert "Reads all ~2,000,000 rows" in prompt
    assert "customer_id integer" in prompt
    assert "orders_pkey" in prompt


# ---------- check_create_index_sql ----------

@pytest.mark.parametrize(
    "sql",
    [
        GOOD_SQL,
        GOOD_SQL + ";",
        "create index idx_a on orders (customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_a ON public.orders USING btree (customer_id)",
        "CREATE INDEX idx_email ON orders (lower(status))",
    ],
)
def test_valid_create_index_is_accepted(sql):
    assert check_create_index_sql(sql, ["orders"]).upper().startswith("CREATE INDEX")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "CREATE INDEX idx_a ON orders (customer_id); DROP TABLE orders",
        "CREATE INDEX CONCURRENTLY idx_a ON orders (customer_id)",
        "CREATE UNIQUE INDEX idx_a ON orders (customer_id)",
        "CREATE INDEX idx_a ON customers (city)",        # table not in this query
        "CREATE INDEX idx_a ON orders",                   # no columns
    ],
)
def test_unsafe_or_wrong_sql_is_rejected(sql):
    with pytest.raises(InvalidProposalError):
        check_create_index_sql(sql, ["orders"])


# ---------- parse_proposal ----------

def test_valid_proposal_is_parsed():
    proposal = parse_proposal(
        {"fix_type": "create_index", "sql": GOOD_SQL, "reason": "Avoids the full scan."},
        allowed_tables=["orders"],
    )

    assert proposal.fix_type == "create_index"
    assert proposal.sql == GOOD_SQL
    assert proposal.reason == "Avoids the full scan."


def test_no_change_proposal_has_no_sql():
    proposal = parse_proposal(
        {"fix_type": "no_change", "sql": None, "reason": "Already indexed."},
        allowed_tables=["orders"],
    )

    assert proposal.sql is None


@pytest.mark.parametrize(
    "data",
    [
        {"fix_type": "drop_table", "sql": "DROP TABLE orders", "reason": "x"},   # unknown type
        {"fix_type": "create_index", "sql": "", "reason": "x"},                 # sql missing
        {"fix_type": "create_index", "sql": GOOD_SQL},                           # reason missing
        {},                                                                      # empty
    ],
)
def test_bad_proposals_are_rejected(data):
    with pytest.raises(InvalidProposalError):
        parse_proposal(data, allowed_tables=["orders"])


# ---------- propose_fix (whole flow, fake LLM) ----------

def test_propose_fix_returns_validated_proposal():
    llm = FakeLLM(
        '```json\n{"fix_type": "create_index", "sql": "' + GOOD_SQL + '", '
        '"reason": "Lets Postgres jump to one customer, already sorted by date."}\n```'
    )

    proposal = propose_fix(llm, QUERY, PLAN_TEXT, PROBLEMS, COLUMNS, INDEXES)

    assert proposal.sql == GOOD_SQL
    [(system_prompt, user_prompt)] = llm.prompts
    assert "CREATE INDEX" in system_prompt
    assert QUERY in user_prompt


def test_propose_fix_rejects_dangerous_llm_answer():
    llm = FakeLLM('{"fix_type": "create_index", "sql": "DROP TABLE orders", "reason": "trust me"}')

    with pytest.raises(InvalidProposalError):
        propose_fix(llm, QUERY, PLAN_TEXT, PROBLEMS, COLUMNS, INDEXES)