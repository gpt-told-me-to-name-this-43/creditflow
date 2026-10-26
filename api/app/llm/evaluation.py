"""Eval распознавания потребности (`make eval-intent`, issue #8).

Датасет — `tests/eval/intent.jsonl`: фраза, категория и ожидаемые `purpose_code`,
`requested_amount_rub`, `term_months` (`null` — поле не должно быть предложено). Режимы:
«только правила» (`DisabledClient`) и «правила + LLM». Метрики: точность по полям и по
фразе целиком, p50/p95 латентности `/interpret`, токены провайдера.
"""

import json
import statistics
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMClient, LlmResult, LlmTask
from app.llm.client import DisabledClient
from app.llm.intent import interpret_text
from app.llm.intent_rules import FIELDS


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    text: str
    expected: dict[str, Any]
    author: str


def load_cases(path: Path) -> list[Case]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            cases.append(
                Case(row["id"], row["category"], row["text"], row["expected"], row["author"])
            )
    return cases


class MeteredClient:
    """Прокси клиента: считает вызовы, токены и латентность провайдера."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.mode = inner.mode
        self.calls = 0
        self.tokens = 0
        self.failures = 0

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult:
        if self.mode != "disabled":
            self.calls += 1
        try:
            result = await self.inner.complete(task, prompt_version, context, schema)
        except Exception:
            if self.mode != "disabled":
                self.failures += 1
            raise
        self.tokens += result.usage.get("total_tokens", 0)
        return result


@dataclass
class CaseResult:
    case: Case
    predicted: dict[str, Any]
    status: str
    latency_ms: float

    @property
    def field_ok(self) -> dict[str, bool]:
        return {f: self.predicted.get(f) == self.case.expected.get(f) for f in FIELDS}

    @property
    def phrase_ok(self) -> bool:
        return all(self.field_ok.values())


@dataclass
class Report:
    label: str
    results: list[CaseResult]
    calls: int = 0
    tokens: int = 0
    notes: list[str] = field(default_factory=list)
    failures: int = 0

    def accuracy(self, name: str | None = None, *, category: str | None = None) -> float:
        rows = [r for r in self.results if category is None or r.case.category == category]
        if not rows:
            return 0.0
        hits = sum(r.phrase_ok if name is None else r.field_ok[name] for r in rows)
        return hits / len(rows)

    def latency(self, q: float) -> float:
        values = sorted(r.latency_ms for r in self.results)
        if len(values) < 2:
            return values[0] if values else 0.0
        return statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]


async def evaluate(
    cases: list[Case], llm: LLMClient | None, label: str, timeout_seconds: float = 20
) -> Report:
    client = MeteredClient(llm or DisabledClient())
    results = []
    for case in cases:
        started = time.perf_counter()
        response = await interpret_text(case.text, client, timeout_seconds)
        elapsed = (time.perf_counter() - started) * 1000
        predicted: dict[str, Any] = {
            name: (
                getattr(response.suggestion, name).value
                if getattr(response.suggestion, name)
                else None
            )
            for name in FIELDS
        }
        predicted["purpose_code"] = (
            str(predicted["purpose_code"]) if predicted["purpose_code"] else None
        )
        results.append(CaseResult(case, predicted, response.status.value, elapsed))
    return Report(label, results, client.calls, client.tokens, failures=client.failures)


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


def summary_table(reports: list[Report]) -> str:
    head = (
        "| Режим | Цель | Сумма | Срок | Фраза целиком | p50, мс | p95, мс "
        + "| Вызовов LLM | Токенов |"
    )
    lines = [head, "|---|---|---|---|---|---|---|---|---|"]
    for r in reports:
        lines.append(
            f"| {r.label} | {_pct(r.accuracy('purpose_code'))} | "
            f"{_pct(r.accuracy('requested_amount_rub'))} | {_pct(r.accuracy('term_months'))} | "
            f"{_pct(r.accuracy())} | {r.latency(0.5):.0f} | {r.latency(0.95):.0f} | "
            f"{r.calls} | {r.tokens} |"
        )
    return "\n".join(lines)


def category_table(reports: list[Report]) -> str:
    categories = list(dict.fromkeys(r.case.category for r in reports[0].results))
    lines = [
        "| Категория | Фраз | " + " | ".join(r.label for r in reports) + " |",
        "|---|---|" + "---|" * len(reports),
    ]
    for c in categories:
        n = sum(1 for r in reports[0].results if r.case.category == c)
        cells = " | ".join(_pct(r.accuracy(category=c)) for r in reports)
        lines.append(f"| {c} | {n} | {cells} |")
    return "\n".join(lines)


def misses_table(report: Report) -> str:
    lines = ["| ID | Фраза | Ожидалось | Получено |", "|---|---|---|---|"]
    for r in report.results:
        if r.phrase_ok:
            continue
        expected = ", ".join(str(r.case.expected.get(f)) for f in FIELDS)
        got = ", ".join(str(r.predicted.get(f)) for f in FIELDS)
        text = r.case.text.replace("|", "\\|")
        if len(text) > 70:
            text = text[:67] + "…"
        lines.append(f"| {r.case.id} | {text} | {expected} | {got} |")
    return "\n".join(lines) if len(lines) > 2 else "Промахов нет."
