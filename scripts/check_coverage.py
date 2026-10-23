"""Раздельный порог покрытия `app/scoring` (issue #6): строки ≥ 95%, ветки ≥ 90%.

`--cov-fail-under` при `--cov-branch` сравнивает ОДИН общий процент (строки и ветки вместе),
поэтому 99% строк маскируют, например, 80% веток. Скрипт читает отчёт coverage.py
(`pytest --cov-report=json:coverage.json`) и проверяет каждый показатель отдельно.

    uv run python ../scripts/check_coverage.py coverage.json --lines 95 --branches 90
"""

import argparse
import json
import sys
from pathlib import Path


def percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path, help="JSON-отчёт coverage.py")
    parser.add_argument("--lines", type=float, required=True, help="минимум покрытия строк, %%")
    parser.add_argument("--branches", type=float, required=True, help="минимум покрытия веток, %%")
    args = parser.parse_args(argv)

    totals = json.loads(args.report.read_text(encoding="utf-8"))["totals"]
    if "num_branches" not in totals:
        print("В отчёте нет веток: запустите pytest с --cov-branch", file=sys.stderr)
        return 2
    lines = percent(totals["covered_lines"], totals["num_statements"])
    branches = percent(totals["covered_branches"], totals["num_branches"])

    ok = True
    for name, value, minimum in (
        ("lines", lines, args.lines),
        ("branches", branches, args.branches),
    ):
        passed = value >= minimum
        ok &= passed
        print(f"{name:<8} {value:6.2f}% (min {minimum:g}%) {'OK' if passed else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
