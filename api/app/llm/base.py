"""Общие типы LLM-слоя: задачи, результат, ошибки, протокол клиента, `context_hash`."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel

from app.schemas.enums import FallbackReason


class LlmTask(StrEnum):
    EXTRACT_INTENT = "extract_intent"
    EXPLAIN_RISK = "explain_risk"


# Имя схемы в response_format.json_schema (issue #8).
SCHEMA_NAMES = {LlmTask.EXTRACT_INTENT: "intent", LlmTask.EXPLAIN_RISK: "risk_report"}


@dataclass(frozen=True)
class LlmResult:
    """Финальный контент модели (без рассуждений) и метаданные вызова для логов и БД."""

    content: str
    model_id: str
    provider: str
    prompt_version: str
    context_hash: str
    latency_ms: int
    usage: dict[str, int] = field(default_factory=dict)


class LlmError(Exception):
    """Сбой вызова. `reason` — значение `fallback_reason` заключения. Текст исключения
    никогда не содержит промпт, ответ модели или ключ."""

    reason: FallbackReason = FallbackReason.UNAVAILABLE


class LlmDisabled(LlmError):
    reason = FallbackReason.DISABLED


class LlmUnavailable(LlmError):
    reason = FallbackReason.UNAVAILABLE


class LlmTimeout(LlmError):
    reason = FallbackReason.TIMEOUT


class LlmReplayMiss(LlmError):
    reason = FallbackReason.REPLAY_MISS


class LlmInvalidOutput(LlmError):
    reason = FallbackReason.INVALID_OUTPUT


class LLMClient(Protocol):
    """issue #8: `complete(task, prompt_version, context, schema) -> LlmResult`.

    Клиент возвращает сырой финальный контент; разбор и валидацию по `schema` делает
    вызывающий (`app.llm.parsing`) — одинаково для живого провайдера и replay.
    """

    mode: str

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult: ...


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def context_hash(task: LlmTask, prompt_version: str, context: Mapping[str, Any]) -> str:
    """sha256(task + prompt_version + canonical_json(context)) — ключ replay-фикстуры."""
    payload = f"{task.value}\n{prompt_version}\n{canonical_json(dict(context))}"
    return hashlib.sha256(payload.encode()).hexdigest()
