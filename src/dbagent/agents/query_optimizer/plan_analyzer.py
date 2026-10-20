"""Read an EXPLAIN plan (JSON) and point out likely performance problems.

A plan is a tree: each node is one step (scan, sort, join...), and its
"Plans" list holds the child steps that feed data into it.
"""

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanProblem:
    """One problem (or hint) spotted in a plan."""

    kind: str                     # "full_table_scan" or "sort"
    severity: str                 # "high" or "info"
    table: str | None
    detail: str
    filter: str | None = None
    sort_key: tuple[str, ...] = ()


def all_nodes(node: dict) -> Iterator[dict]:
    """Yield this node and every node below it (depth-first)."""
    yield node
    for child in node.get("Plans", []):
        yield from all_nodes(child)


def get_tables(plan: dict) -> list[str]:
    """Names of all tables the plan reads, in a stable sorted order."""
    return sorted({node["Relation Name"] for node in all_nodes(plan) if "Relation Name" in node})


def plan_to_text(plan: dict) -> list[str]:
    """Human-readable outline of the plan tree, one line per node."""
    lines = []

    def walk(node: dict, depth: int) -> None:
        name = node["Node Type"]
        if node.get("Parallel Aware"):
            name = "Parallel " + name
        parts = [name]
        if "Relation Name" in node:
            parts.append(f"on {node['Relation Name']}")
        if "Index Name" in node:
            parts.append(f"using {node['Index Name']}")
        parts.append(f"(est. rows {node['Plan Rows']}, cost {node['Total Cost']})")
        lines.append("  " * depth + "-> " + " ".join(parts))
        for child in node.get("Plans", []):
            walk(child, depth + 1)

    walk(plan, 0)
    return lines


def find_problems(
    plan: dict,
    table_sizes: dict[str, int],
    min_table_rows: int = 10_000,
    max_selectivity: float = 0.05,
) -> list[PlanProblem]:
    """Return problems for the plan.

    A full table scan is reported when a filtered Seq Scan reads a big table
    (>= min_table_rows) but expects to keep only a small fraction of it
    (<= max_selectivity). That pattern usually means a missing index.
    """
    problems = []
    for node in all_nodes(plan):
        node_type = node["Node Type"]

        if node_type == "Seq Scan" and "Filter" in node:
            table = node["Relation Name"]
            total_rows = table_sizes.get(table, 0)
            if total_rows < min_table_rows:
                continue  # scanning a small table is cheap; not worth an index
            # Note: for parallel scans "Plan Rows" is per worker, so this is a
            # rough estimate. Good enough to tell "a few rows" from "most rows".
            expected_rows = node["Plan Rows"]
            selectivity = expected_rows / total_rows
            if selectivity <= max_selectivity:
                problems.append(
                    PlanProblem(
                        kind="full_table_scan",
                        severity="high",
                        table=table,
                        filter=node["Filter"],
                        detail=(
                            f"Reads all ~{total_rows:,} rows of '{table}' to keep about "
                            f"{expected_rows:,} (filter {node['Filter']}). "
                            "An index on the filtered column(s) could avoid this."
                        ),
                    )
                )

        elif node_type == "Sort":
            keys = tuple(node.get("Sort Key", []))
            problems.append(
                PlanProblem(
                    kind="sort",
                    severity="info",
                    table=None,
                    sort_key=keys,
                    detail=(
                        f"Sorts rows by {', '.join(keys)}. An index that also contains "
                        "these columns (in this order) could return rows already sorted."
                    ),
                )
            )

    # Most important first: "high" problems before "info" ones.
    problems.sort(key=lambda problem: problem.severity != "high")
    return problems