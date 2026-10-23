"""The Query Optimizer agent, built as a LangGraph state graph.

    START -> investigate -> propose -> verify -> END
                              ^          |
                              +- retry --+   (if the fix did not help)

Each NODE is one step. It reads the shared STATE and returns the fields it changed.
Each ROUTER looks at the state and decides which node runs next.
The agent stops as soon as `status` is set.
"""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from dbagent.agents.query_optimizer.fix_proposer import InvalidProposalError
from dbagent.agents.query_optimizer.sandbox import SandboxError
from dbagent.core.llm import LLMError
from dbagent.telemetry.explain import UnsafeQueryError

# Errors that end the run with status "error" instead of crashing the agent.
EXPECTED_ERRORS = (UnsafeQueryError, SandboxError, LLMError)


class OptimizerState(TypedDict):
    """Everything the agent knows during one run."""

    query: str                    # the slow query (with $1, $2 placeholders)
    max_attempts: int             # how many fixes the agent may try
    investigation: Any            # Investigation, filled by the investigate node
    proposal: Any                 # latest FixProposal (None if the last answer was invalid)
    result: Any                   # latest SandboxResult
    attempts: list[dict]          # one entry per tried fix: sql, reason, outcome
    log: list[str]                # human-readable trace of what the agent did
    status: str                   # "" while running; then fixed / no_problem / no_change / gave_up / error


def new_state(query: str, max_attempts: int = 3) -> OptimizerState:
    """Starting state for one run."""
    return OptimizerState(
        query=query, max_attempts=max_attempts, investigation=None, proposal=None,
        result=None, attempts=[], log=[], status="",
    )


def feedback_from_attempts(attempts: list[dict]) -> list[str]:
    """Turn failed attempts into short lines for the LLM prompt."""
    return [f"{attempt['sql'] or '(invalid answer)'} -> {attempt['outcome']}" for attempt in attempts]


# ---------- nodes ----------

def make_nodes(tools):
    """Create the node functions. `tools` does the real work (see tools.py)."""

    def investigate(state: OptimizerState) -> dict:
        try:
            investigation = tools.investigate(state["query"])
        except EXPECTED_ERRORS as error:
            return {"status": "error", "log": state["log"] + [f"investigate: stopped - {error}"]}
        high = [p for p in investigation.problems if p.severity == "high"]
        log = state["log"] + [f"investigate: {len(investigation.problems)} problem(s), {len(high)} high"]
        if not high:
            return {"investigation": investigation, "status": "no_problem", "log": log + ["nothing to fix"]}
        return {"investigation": investigation, "log": log}

    def propose(state: OptimizerState) -> dict:
        attempt_number = len(state["attempts"]) + 1
        feedback = feedback_from_attempts(state["attempts"])
        try:
            proposal = tools.propose(state["investigation"], feedback)
        except InvalidProposalError as error:
            attempts = state["attempts"] + [{"sql": None, "reason": "", "outcome": f"invalid answer: {error}"}]
            log = state["log"] + [f"propose #{attempt_number}: rejected invalid LLM answer - {error}"]
            status = "gave_up" if len(attempts) >= state["max_attempts"] else ""
            return {"proposal": None, "attempts": attempts, "log": log, "status": status}
        except EXPECTED_ERRORS as error:
            return {"status": "error", "log": state["log"] + [f"propose: stopped - {error}"]}

        if proposal.fix_type == "no_change":
            log = state["log"] + [f"propose #{attempt_number}: LLM says no change - {proposal.reason}"]
            return {"proposal": proposal, "status": "no_change", "log": log}
        log = state["log"] + [f"propose #{attempt_number}: {proposal.sql}"]
        return {"proposal": proposal, "log": log}

    def verify(state: OptimizerState) -> dict:
        proposal = state["proposal"]
        try:
            result = tools.verify(state["investigation"], proposal.sql)
        except EXPECTED_ERRORS as error:
            return {"status": "error", "log": state["log"] + [f"verify: stopped - {error}"]}

        if result.improved:
            outcome = f"worked: {result.before_ms:.2f} ms -> {result.after_ms:.2f} ms ({result.speedup:.0f}x)"
        elif not result.index_used:
            outcome = f"index was not used by Postgres ({result.plan_after})"
        else:
            outcome = f"not enough gain: {result.before_ms:.2f} ms -> {result.after_ms:.2f} ms"
        attempts = state["attempts"] + [{"sql": proposal.sql, "reason": proposal.reason, "outcome": outcome}]
        log = state["log"] + [f"verify: {outcome}"]

        if result.improved:
            status = "fixed"
        elif len(attempts) >= state["max_attempts"]:
            status = "gave_up"
        else:
            status = ""  # try again
        return {"result": result, "attempts": attempts, "log": log, "status": status}

    return investigate, propose, verify


# ---------- routers ----------

def route_after_investigate(state: OptimizerState) -> str:
    return "end" if state["status"] else "propose"


def route_after_propose(state: OptimizerState) -> str:
    if state["status"]:
        return "end"
    if state["proposal"] is None:
        return "propose"          # the answer was invalid: ask again
    return "verify"


def route_after_verify(state: OptimizerState) -> str:
    return "end" if state["status"] else "propose"


# ---------- graph ----------

def build_agent(tools):
    """Wire the nodes and routers into a runnable LangGraph agent."""
    investigate, propose, verify = make_nodes(tools)

    graph = StateGraph(OptimizerState)
    graph.add_node("investigate", investigate)
    graph.add_node("propose", propose)
    graph.add_node("verify", verify)

    graph.add_edge(START, "investigate")
    graph.add_conditional_edges("investigate", route_after_investigate, {"propose": "propose", "end": END})
    graph.add_conditional_edges("propose", route_after_propose, {"propose": "propose", "verify": "verify", "end": END})
    graph.add_conditional_edges("verify", route_after_verify, {"propose": "propose", "end": END})

    return graph.compile()


def run_optimizer(tools, query: str, max_attempts: int = 3) -> OptimizerState:
    """Run the agent once for one slow query and return the final state."""
    agent = build_agent(tools)
    return agent.invoke(new_state(query, max_attempts))