"""Общие помощники тестов AI-assist (#8): клиенты replay/record/live и управляемый fake.

Режим сценарных тестов задаёт окружение:
- по умолчанию — `ReplayClient` по `llm-replay/` репозитория (CI, без сети);
- `LLM_RECORD=1` — настоящий провайдер из `LLM_*`, ответы пишутся в `llm-replay/`
  (`make llm-record`);
- `LLM_LIVE=1` — настоящий провайдер без записи (`make eval-injection` на модели проверяющего).
"""

import asyncio
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.core.config import DEFAULT_REPLAY_DIR, LLMMode, Settings
from app.llm.base import LLMClient, LlmResult, LlmTask, context_hash
from app.llm.client import DisabledClient, OpenAICompatibleClient, RecordingClient, ReplayClient
from tests.conftest import TEST_DATABASE_URL, TEST_SECRET_KEY

LLM_RECORD = os.environ.get("LLM_RECORD") == "1"
LLM_LIVE = os.environ.get("LLM_LIVE") == "1"
REPLAY_DIR = Path(os.environ.get("LLM_REPLAY_DIR") or DEFAULT_REPLAY_DIR)


def live_settings() -> Settings:
    """`LLM_*` из окружения (как у api); остальное — тестовое."""
    settings = Settings(
        app_secret_key=TEST_SECRET_KEY, database_url=TEST_DATABASE_URL, app_env="test"
    )
    if settings.llm_mode is not LLMMode.OPENAI or not settings.llm_base_url:
        raise RuntimeError("LLM_RECORD/LLM_LIVE: нужны LLM_MODE=openai, LLM_BASE_URL, LLM_MODEL")
    return settings


def scenario_client() -> LLMClient:
    if LLM_RECORD:
        if os.environ.get("LLM_MODE") != "openai":
            raise RuntimeError("Запись требует явного LLM_MODE=openai")
        return RecordingClient(OpenAICompatibleClient(live_settings()), REPLAY_DIR)
    if LLM_LIVE:
        return OpenAICompatibleClient(live_settings())
    if os.environ.get("LLM_MODE") == "disabled":
        return DisabledClient()
    return ReplayClient(REPLAY_DIR)


@dataclass
class Call:
    task: LlmTask
    prompt_version: str
    context: dict[str, Any]


@dataclass
class FakeLLM:
    """Сценарный клиент: ответы по очереди, задержка, ворота `gate` для гонок.

    `responses` — строки контента или исключения; последний элемент повторяется.
    """

    responses: list[str | BaseException]
    delay: float = 0.0
    gate: asyncio.Event | None = None
    model: str = "fake/model-1"
    mode: str = "openai"
    calls: list[Call] = field(default_factory=list)
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult:
        self.calls.append(Call(task, prompt_version, dict(context)))
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        response = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(response, BaseException):
            raise response
        return LlmResult(
            content=response,
            model_id=self.model,
            provider="fake",
            prompt_version=prompt_version,
            context_hash=context_hash(task, prompt_version, context),
            latency_ms=int(self.delay * 1000),
        )


def by_task(fake: FakeLLM, task: LlmTask) -> list[Call]:
    return [c for c in fake.calls if c.task is task]


Responder = Callable[[dict[str, Any]], str]
