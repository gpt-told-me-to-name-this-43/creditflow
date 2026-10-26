"""`LLMClient`: OpenAI-совместимый Chat Completions, replay и disabled (design.md §3.6).

- `OpenAICompatibleClient` — SDK `openai` (`AsyncOpenAI(base_url, api_key, timeout,
  max_retries=0)`): один повтор на 429/5xx/таймаут с учётом `Retry-After`, семафор
  `LLM_MAX_CONCURRENCY`, circuit breaker; `X-Request-ID` уходит провайдеру.
- `ReplayClient` — ответы из `llm-replay/{task}/{prompt_version}/{context_hash}.json`.
- `DisabledClient` — всегда `LlmDisabled`: только правила и шаблоны.
- `RecordingClient` — обёртка для `make llm-record`: пишет фикстуры replay.

Логи вызова: задача, модель, `prompt_version`, `context_hash`, латентность, `usage`, статус —
без промптов, ответов и ключа. Исключения наружу — только `LlmError` без тел ответов.
"""

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import openai
from pydantic import BaseModel

from app.core.config import LLMMode, Settings, StructuredOutput
from app.core.logs import get_logger
from app.core.request_context import request_id_var
from app.llm.base import (
    SCHEMA_NAMES,
    LLMClient,
    LlmDisabled,
    LlmError,
    LlmInvalidOutput,
    LlmReplayMiss,
    LlmResult,
    LlmTask,
    LlmTimeout,
    LlmUnavailable,
    context_hash,
)
from app.llm.breaker import CircuitBreaker
from app.llm.prompts import build_messages

logger = get_logger("app.llm")

RETRY_AFTER_CAP_SECONDS = 10.0  # дольше ждать не имеет смысла: бюджет задачи меньше
DEFAULT_RETRY_DELAY_SECONDS = 0.5
LOCAL_HOSTS = frozenset({"localhost", "host.docker.internal", "ollama", "vllm", "lmstudio"})

Sleep = Callable[[float], Awaitable[None]]


def llm_json_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """Строгая JSON Schema ответа (все поля required, additionalProperties: false)."""
    explicit: dict[str, Any] | None = getattr(schema, "LLM_JSON_SCHEMA", None)
    return explicit if explicit is not None else schema.model_json_schema()


def provider_name(base_url: str | None) -> str:
    return (urlsplit(base_url).hostname or "unknown") if base_url else "unknown"


def is_local_host(host: str) -> bool:
    if host in LOCAL_HOSTS or "." not in host:  # имя сервиса compose
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return host.endswith((".local", ".internal", ".localhost"))
    return address.is_private or address.is_loopback


def insecure_url_warning(settings: Settings) -> str | None:
    """issue #8: http на нелокальном хосте — предупреждение при старте (ключ уйдёт открыто)."""
    if settings.llm_mode is not LLMMode.OPENAI or not settings.llm_base_url:
        return None
    parts = urlsplit(settings.llm_base_url)
    if parts.scheme == "http" and parts.hostname and not is_local_host(parts.hostname):
        return f"LLM_BASE_URL: http на нелокальном хосте {parts.hostname} — используйте https"
    return None


def model_for(settings: Settings, task: LlmTask) -> str | None:
    specific = {
        LlmTask.EXTRACT_INTENT: settings.llm_model_intent,
        LlmTask.EXPLAIN_RISK: settings.llm_model_explain,
    }[task]
    return specific or settings.llm_model


def _retry_after(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        return max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return None


def _usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    return {
        k: int(v)
        for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(v := getattr(usage, k, None), int)
    }


def _http_client(timeout: float) -> httpx.AsyncClient:
    """Прокси из окружения (HTTPS_PROXY, NO_PROXY) учитываются: провайдер обычно внешний.
    Если httpx не разбирает NO_PROXY (например, «[::1]»), api всё равно стартует: прокси
    берётся из HTTPS_PROXY без исключений — LLM не должна ронять приложение."""
    try:
        return httpx.AsyncClient(timeout=timeout)
    except (httpx.InvalidURL, ValueError):
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
        logger.warning("llm.proxy_env_unparsed", proxy_configured=proxy is not None)
        return httpx.AsyncClient(timeout=timeout, trust_env=False, proxy=proxy)


class OpenAICompatibleClient:
    mode: str = LLMMode.OPENAI.value

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        breaker: CircuitBreaker | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.settings = settings
        self.provider = provider_name(settings.llm_base_url)
        self.breaker = breaker or CircuitBreaker()
        self._semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
        self._sleep = sleep
        self._client = openai.AsyncOpenAI(
            base_url=settings.llm_base_url,
            # Локальным рантаймам ключ не нужен, а SDK требует непустой
            api_key=settings.llm_api_key or "not-needed",
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
            http_client=http_client or _http_client(settings.llm_timeout_seconds),
        )

    @property
    def configured(self) -> bool:
        return bool(self.settings.llm_base_url and self.settings.llm_model)

    def _response_format(self, task: LlmTask, schema: type[BaseModel]) -> dict[str, Any] | None:
        mode = self.settings.llm_structured_output
        if mode is StructuredOutput.JSON_SCHEMA:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAMES[task],
                    "strict": True,
                    "schema": llm_json_schema(schema),
                },
            }
        if mode is StructuredOutput.JSON_OBJECT:
            return {"type": "json_object"}
        return None

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult:
        model = model_for(self.settings, task)
        if not self.configured or model is None:
            raise LlmUnavailable("LLM не настроена: нужны LLM_BASE_URL и LLM_MODEL")
        digest = context_hash(task, prompt_version, context)
        log = logger.bind(
            task=task.value, model=model, prompt_version=prompt_version, context_hash=digest
        )
        if not self.breaker.allow():
            log.info("llm.call", status="circuit_open", latency_ms=0)
            raise LlmUnavailable("circuit breaker открыт")
        request: dict[str, Any] = {
            "model": model,
            "messages": build_messages(
                task,
                prompt_version,
                context,
                self.settings.llm_structured_output,
                llm_json_schema(schema),
            ),
            "temperature": self.settings.llm_temperature,
            "max_tokens": self.settings.llm_max_tokens,
        }
        if self.settings.llm_seed is not None:
            request["seed"] = self.settings.llm_seed
        response_format = self._response_format(task, schema)
        if response_format is not None:
            request["response_format"] = response_format
        if self.settings.llm_extra_body:
            request["extra_body"] = dict(self.settings.llm_extra_body)
        request_id = request_id_var.get()
        if request_id:
            request["extra_headers"] = {"X-Request-ID": request_id}
        try:
            result = await self._call_with_retry(request, log, model, prompt_version, digest)
        except LlmInvalidOutput:  # провайдер ответил: для breaker это не сбой
            self.breaker.record_success()
            raise
        except LlmError:
            self.breaker.record_failure()
            raise
        except asyncio.CancelledError:  # бюджет задачи истёк посреди вызова
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return result

    async def _call_with_retry(
        self,
        request: dict[str, Any],
        log: Any,
        model: str,
        prompt_version: str,
        digest: str,
    ) -> LlmResult:
        for attempt in (1, 2):
            started = time.monotonic()
            delay: float | None = None
            error: LlmError
            try:
                async with self._semaphore:
                    started = time.monotonic()
                    response = await self._client.chat.completions.create(**request)
            except openai.APITimeoutError:
                status, error, delay = "timeout", LlmTimeout("таймаут провайдера"), 0.0
            except openai.APIStatusError as exc:
                code = exc.status_code
                status, error = f"http_{code}", LlmUnavailable(f"провайдер ответил HTTP {code}")
                if code == 429 or code >= 500:
                    delay = _retry_after(exc.response)
                    if delay is None:
                        delay = DEFAULT_RETRY_DELAY_SECONDS
            except openai.APIConnectionError:
                status, error = "connection_error", LlmUnavailable("провайдер недоступен")
            except openai.OpenAIError as exc:
                status, error = "error", LlmUnavailable(f"ошибка клиента: {type(exc).__name__}")
            else:
                latency = int((time.monotonic() - started) * 1000)
                usage = _usage(response)
                choices = getattr(response, "choices", None) or []
                content = choices[0].message.content if choices else None
                log.info("llm.call", status="ok", attempt=attempt, latency_ms=latency, usage=usage)
                if not isinstance(content, str) or not content:
                    raise LlmInvalidOutput("пустой ответ модели")
                return LlmResult(
                    content=content,
                    model_id=getattr(response, "model", None) or model,
                    provider=self.provider,
                    prompt_version=prompt_version,
                    context_hash=digest,
                    latency_ms=latency,
                    usage=usage,
                )
            latency = int((time.monotonic() - started) * 1000)
            log.warning("llm.call", status=status, attempt=attempt, latency_ms=latency)
            if attempt == 2 or delay is None or delay > RETRY_AFTER_CAP_SECONDS:
                raise error
            await self._sleep(delay)
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        await self._client.close()


class DisabledClient:
    mode: str = LLMMode.DISABLED.value

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult:
        raise LlmDisabled("LLM_MODE=disabled")


def fixture_path(root: Path, task: LlmTask, prompt_version: str, digest: str) -> Path:
    return root / task.value / prompt_version / f"{digest}.json"


class ReplayClient:
    """Детерминированно и без сети; промах — `REPLAY_MISS`, дальше шаблон или правила."""

    mode: str = LLMMode.REPLAY.value

    def __init__(self, root: Path) -> None:
        self.root = root

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult:
        digest = context_hash(task, prompt_version, context)
        path = fixture_path(self.root, task, prompt_version, digest)
        log = logger.bind(task=task.value, prompt_version=prompt_version, context_hash=digest)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            log.info("llm.call", status="replay_miss", latency_ms=0)
            raise LlmReplayMiss("нет записанного ответа для контекста") from None
        except ValueError:
            log.warning("llm.call", status="replay_corrupt", latency_ms=0)
            raise LlmReplayMiss("повреждённая replay-фикстура") from None
        log.info("llm.call", status="ok", model=data.get("model"), latency_ms=0)
        return LlmResult(
            content=str(data["response"]),
            model_id=str(data.get("model") or "replay"),
            provider=str(data.get("provider") or "replay"),
            prompt_version=prompt_version,
            context_hash=digest,
            latency_ms=0,
            usage={k: int(v) for k, v in (data.get("usage") or {}).items()},
        )


class RecordingClient:
    """Вызывает настоящего провайдера и сохраняет ответ как replay-фикстуру.

    В фикстуру пишутся ответ, модель, провайдер и дата — без промпта и ключа; контекст уже
    минимизирован (`app.llm.pii`) и восстанавливается из кода по `context_hash`.
    """

    def __init__(self, inner: OpenAICompatibleClient, root: Path) -> None:
        self.inner, self.root = inner, root
        self.mode = inner.mode
        self.recorded: list[Path] = []
        self.failed = 0

    async def complete(
        self,
        task: LlmTask,
        prompt_version: str,
        context: Mapping[str, Any],
        schema: type[BaseModel],
    ) -> LlmResult:
        digest = context_hash(task, prompt_version, context)
        path = fixture_path(self.root, task, prompt_version, digest)
        # Запись дополняет набор. Существующие ответы никогда не перезаписываются
        # и не требуют платного вызова. Для новой модели используйте новый каталог.
        if path.exists():
            return await ReplayClient(self.root).complete(task, prompt_version, context, schema)
        try:
            result = await self.inner.complete(task, prompt_version, context, schema)
        except Exception:
            self.failed += 1
            raise
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "task": task.value,
            "prompt_version": prompt_version,
            "context_hash": result.context_hash,
            "model": result.model_id,
            "provider": result.provider,
            "recorded_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "usage": result.usage,
            "response": result.content,
        }
        # exclusive create защищает также от параллельных записывающих процессов.
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        except FileExistsError:
            return await ReplayClient(self.root).complete(task, prompt_version, context, schema)
        self.recorded.append(path)
        return result


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_mode is LLMMode.OPENAI:
        return OpenAICompatibleClient(settings)
    if settings.llm_mode is LLMMode.REPLAY:
        return ReplayClient(settings.llm_replay_dir)
    return DisabledClient()
