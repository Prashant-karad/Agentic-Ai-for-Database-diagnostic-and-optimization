"""Tests for the LangGraph Query Optimizer agent, using mock tools (no DB, no LLM)."""

from dbagent.agents.query_optimizer.agent import feedback_from_attempts, run_optimizer
from dbagent.agents.query_optimizer.fix_proposer import FixProposal, InvalidProposalError
from dbagent.agents.query_optimizer.plan_analyzer import PlanProblem
from dbagent.agents.query_optimizer.sandbox import SandboxError, SandboxResult
from dbagent.agents.query_optimizer.tools import Investigation

QUERY = "SELECT id FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT $2"
GOOD_FIX = "CREATE INDEX idx_good ON orders (customer_id, created_at DESC)"
BAD_FIX = "CREATE INDEX idx_bad ON orders (status)"

HIGH_PROBLEM = PlanProblem(kind="full_table_scan", severity="high", table="orders", detail="full scan")


def make_investigation(problems):
    return Investigation(
        query=QUERY, table="orders", plan_text=[], problems=problems,
        columns={"orders": []}, indexes={}, samples=[{1: 1, 2: 10}],
    )


def make_result(improved: bool) -> SandboxResult:
    return SandboxResult(
        before_ms=70.0, after_ms=0.06 if improved else 70.0, speedup=1166.0 if improved else 1.0,
        index_used=improved, improved=improved,
        plan_before="Seq Scan on orders", plan_after="Index Scan using idx_good" if improved else "Seq Scan on orders",
    )


class MockTools:
    """Plays a script: `answers` are what the LLM 'proposes', one per call."""

    def __init__(self, answers, problems=(HIGH_PROBLEM,), investigate_error=None):
        self.answers = list(answers)
        self.problems = list(problems)
        self.investigate_error = investigate_error
        self.feedback_seen: list[list[str]] = []

    def investigate(self, query):
        if self.investigate_error:
            raise self.investigate_error
        return make_investigation(self.problems)

    def propose(self, investigation, feedback):
        self.feedback_seen.append(list(feedback))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def verify(self, investigation, fix_sql):
        return make_result(improved=(fix_sql == GOOD_FIX))


def index_fix(sql):
    return FixProposal(fix_type="create_index", sql=sql, reason="test")


def test_good_fix_on_first_try_is_fixed():
    tools = MockTools([index_fix(GOOD_FIX)])

    state = run_optimizer(tools, QUERY)

    assert state["status"] == "fixed"
    assert len(state["attempts"]) == 1
    assert state["result"].improved is True


def test_agent_retries_with_feedback_after_a_bad_fix():
    tools = MockTools([index_fix(BAD_FIX), index_fix(GOOD_FIX)])

    state = run_optimizer(tools, QUERY)

    assert state["status"] == "fixed"
    assert [a["sql"] for a in state["attempts"]] == [BAD_FIX, GOOD_FIX]
    assert tools.feedback_seen[0] == []                      # first try: no feedback yet
    assert BAD_FIX in tools.feedback_seen[1][0]              # second try: told what failed
    assert "not used" in tools.feedback_seen[1][0]


def test_agent_gives_up_after_max_attempts():
    tools = MockTools([index_fix(BAD_FIX)] * 3)

    state = run_optimizer(tools, QUERY, max_attempts=3)

    assert state["status"] == "gave_up"
    assert len(state["attempts"]) == 3


def test_invalid_llm_answer_counts_as_attempt_and_agent_asks_again():
    tools = MockTools([InvalidProposalError("DROP TABLE is not allowed"), index_fix(GOOD_FIX)])

    state = run_optimizer(tools, QUERY)

    assert state["status"] == "fixed"
    assert state["attempts"][0]["sql"] is None
    assert "invalid answer" in state["attempts"][0]["outcome"]


def test_no_high_problem_means_llm_is_never_asked():
    tools = MockTools(answers=[], problems=[])

    state = run_optimizer(tools, QUERY)

    assert state["status"] == "no_problem"
    assert tools.feedback_seen == []


def test_llm_saying_no_change_ends_the_run():
    tools = MockTools([FixProposal(fix_type="no_change", sql=None, reason="already optimal")])

    state = run_optimizer(tools, QUERY)

    assert state["status"] == "no_change"


def test_expected_error_ends_with_error_status_instead_of_crashing():
    tools = MockTools([], investigate_error=SandboxError("joins not supported"))

    state = run_optimizer(tools, QUERY)

    assert state["status"] == "error"
    assert "joins not supported" in state["log"][-1]


def test_feedback_from_attempts():
    attempts = [{"sql": BAD_FIX, "reason": "", "outcome": "index was not used"},
                {"sql": None, "reason": "", "outcome": "invalid answer: x"}]

    assert feedback_from_attempts(attempts) == [
        f"{BAD_FIX} -> index was not used",
        "(invalid answer) -> invalid answer: x",
    ]