"""Guard the project's structure: the agent and the simulated shop must stay independent."""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"


def imported_packages(package: str) -> set[str]:
    """Top-level packages imported anywhere inside src/<package>/."""
    found = set()
    for path in (SRC / package).rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"\s*(?:from|import)\s+(\w+)", line)
            if match:
                found.add(match.group(1))
    return found


@pytest.mark.parametrize("package, forbidden", [("shopsim", "dbagent"), ("dbagent", "shopsim")])
def test_packages_do_not_import_each_other(package, forbidden):
    assert forbidden not in imported_packages(package)