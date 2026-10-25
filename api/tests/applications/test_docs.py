"""Документация #7 не расходится с кодом: сценарии S1–S11, демо-учётки, коллекция."""

import ast
import re
import subprocess
import sys

import pytest

from tests.conftest import REPO_ROOT

SCENARIOS = REPO_ROOT / "docs" / "test-scenarios.md"
TESTS = REPO_ROOT / "api" / "tests" / "applications"


def _functions(path: str) -> set[str]:
    tree = ast.parse((TESTS / path).read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}


def test_every_scenario_has_existing_autotests() -> None:
    lines = SCENARIOS.read_text(encoding="utf-8").splitlines()
    rows = [line for line in lines if re.match(r"\| S\d+ ", line)]
    assert [r.split("|")[1].strip() for r in rows] == [f"S{i}" for i in range(1, 12)]
    for row in rows:
        refs = re.findall(r"`([a-z_]+\.py)(?:::(\w+))?`|`::(\w+)`", row.split("|")[4])
        assert refs, row
        current = None
        for file, name, short in refs:
            current = file or current
            assert current and (TESTS / current).is_file(), row
            target = name or short
            if target:
                assert target in _functions(current), f"{current}::{target}"


@pytest.mark.parametrize("script", ["gen_demo_accounts.py", "export_bruno.py"])
def test_generated_docs_are_current(script: str) -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script), "--check"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT / "api",
    )
    assert result.returncode == 0, result.stderr
