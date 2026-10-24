"""scripts/check_coverage.py: строки и ветки проверяются раздельно (issue #6)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_coverage.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_coverage", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def report(tmp_path: Path, lines: tuple[int, int], branches: tuple[int, int] | None) -> str:
    totals = {"covered_lines": lines[0], "num_statements": lines[1]}
    if branches is not None:
        totals |= {"covered_branches": branches[0], "num_branches": branches[1]}
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps({"totals": totals}), "utf-8")
    return str(path)


@pytest.mark.parametrize(
    ("lines", "branches", "code"),
    [
        ((99, 100), (90, 100), 0),  # оба порога ровно на границе и выше
        ((94, 100), (100, 100), 1),  # строки ниже 95
        # 99% строк, 80% веток: общий (396+80)/(400+100) = 95.2% — --cov-fail-under=95
        # пропустил бы, раздельная проверка ловит ветки
        ((396, 400), (80, 100), 1),
        ((0, 0), (0, 0), 0),  # пустой модуль не валит проверку
    ],
)
def test_thresholds_are_independent(
    tmp_path: Path, lines: tuple[int, int], branches: tuple[int, int], code: int
) -> None:
    args = [report(tmp_path, lines, branches), "--lines", "95", "--branches", "90"]
    assert load().main(args) == code


def test_report_without_branches_is_an_error(tmp_path: Path) -> None:
    args = [report(tmp_path, (100, 100), None), "--lines", "95", "--branches", "90"]
    assert load().main(args) == 2
