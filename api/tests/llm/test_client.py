"""OpenAI-совместимый клиент против фейкового `/v1/chat/completions` (respx, #8).

Режимы вывода, повтор на 429 с `Retry-After` и на 5xx, таймаут, невалидный JSON,
рассуждения reasoning-модели, circuit breaker, `X-Request-ID`, логи без ключа и текста.
"""

import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
import respx

from app.core.config import Settings
from app.core.request_context import request_id_var
from app.llm.base import LlmInvalidOutput, LlmTask, LlmTimeout, LlmUnavailable
from app.llm.breaker import CircuitBreaker
from app.llm.client import (
    OpenAICompatibleClient,
    RecordingClient,
    ReplayClient,
    build_llm_client,
    insecure_url_warning,
)
from app.llm.explain import RiskReportLlm
from app.llm.intent import IntentLlmOutput, interpret_text, parse_intent

BASE = "https://llm.test/v1"
KEY = "sk-test-secret-key-must-not-leak"
CONTEXT = {"client_text": "нужно на ремонт", "rules": {"purpose_code": "RENOVATION"}}
ANSWER = {
    "purpose_code": "RENOVATION",
    "requested_amount_rub": 1_000_000,
    "term_months": 24,
    "clarification_question": None,
}


def completion(content: str | None, **message: Any) -> dict[str, Any]:
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": "vendor/model-7b",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, **message},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


@pytest.fixture
def provider() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
def make_client(make_settings: Callable[..., Settings]) -> Callable[..., OpenAICompatibleClient]:
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    def make(**overrides: Any) -> OpenAICompatibleClient:
        values = {
            "llm_mode": "openai",
            "llm_base_url": BASE,
            "llm_api_key": KEY,
            "llm_model": "vendor/model-7b",
            "llm_timeout_seconds": 0.5,
            **overrides,
        }
        client = OpenAICompatibleClient(
            make_settings(**values), http_client=httpx.AsyncClient(trust_env=False), sleep=sleep
        )
        client.sleeps = sleeps  # type: ignore[attr-defined]
        return client

    return make


async def call(client: OpenAICompatibleClient) -> str:
    result = await client.complete(LlmTask.EXTRACT_INTENT, "v1", CONTEXT, IntentLlmOutput)
    return result.content


def sent(route: respx.Route, index: int = -1) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(route.calls[index].request.content)
    return body


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "prompt"])
async def test_success_in_every_output_mode(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient], mode: str
) -> None:
    route = provider.post("/chat/completions").respond(200, json=completion(json.dumps(ANSWER)))
    client = make_client(llm_structured_output=mode)
    result = await client.complete(LlmTask.EXTRACT_INTENT, "v1", CONTEXT, IntentLlmOutput)
    assert parse_intent(result.content).term_months == 24
    assert result.model_id == "vendor/model-7b" and result.usage["total_tokens"] == 120
    body = sent(route)
    system, user = body["messages"][0]["content"], body["messages"][1]["content"]
    if mode == "json_schema":
        rf = body["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "intent" and rf["json_schema"]["strict"] is True
        assert rf["json_schema"]["schema"]["additionalProperties"] is False
        assert "JSON Schema" not in system
    elif mode == "json_object":
        assert body["response_format"] == {"type": "json_object"}
        assert '"additionalProperties":false' in system  # схема — в промпте
    else:
        assert "response_format" not in body
        assert '"additionalProperties":false' in system
    assert "нужно на ремонт" in user and "нужно на ремонт" not in system
    assert "<client_text_untrusted>" in user
    assert body["temperature"] == 0 and body["seed"] == 42 and body["model"] == "vendor/model-7b"
    assert route.calls[-1].request.headers["authorization"] == f"Bearer {KEY}"


async def test_explain_schema_name(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(200, json=completion("{}"))
    await make_client().complete(
        LlmTask.EXPLAIN_RISK, "v1", {"calculation": {}, "client_text": ""}, RiskReportLlm
    )
    assert sent(route)["response_format"]["json_schema"]["name"] == "risk_report"


async def test_429_retried_once_with_retry_after(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}, json={"error": {"message": "slow"}}),
            httpx.Response(200, json=completion(json.dumps(ANSWER))),
        ]
    )
    client = make_client()
    assert json.loads(await call(client))["term_months"] == 24
    assert route.call_count == 2
    assert client.sleeps == [2.0]  # type: ignore[attr-defined]


async def test_retry_after_longer_than_cap_is_not_waited(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(429, headers={"Retry-After": "120"})
    with pytest.raises(LlmUnavailable):
        await call(make_client())
    assert route.call_count == 1


async def test_5xx_retried_once_then_fails(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(500, json={"error": {"message": "x"}})
    client = make_client()
    with pytest.raises(LlmUnavailable) as exc:
        await call(client)
    assert route.call_count == 2
    assert "HTTP 500" in str(exc.value) and KEY not in str(exc.value)
    assert client.breaker.failures == 1


async def test_4xx_not_retried(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(401, json={"error": {"message": "bad key"}})
    with pytest.raises(LlmUnavailable):
        await call(make_client())
    assert route.call_count == 1


async def test_timeout_retried_once(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(LlmTimeout):
        await call(make_client())
    assert route.call_count == 2


async def test_invalid_json_is_invalid_output_not_provider_failure(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    provider.post("/chat/completions").respond(200, json=completion("Конечно! Вот ответ: …"))
    client = make_client()
    content = await call(client)
    with pytest.raises(LlmInvalidOutput):
        parse_intent(content)
    empty = make_client()
    provider.post("/chat/completions").respond(200, json=completion(None))
    with pytest.raises(LlmInvalidOutput):
        await call(empty)
    assert empty.breaker.failures == 0


async def test_reasoning_is_dropped_only_final_content_used(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    content = "<think>Клиент хочет ремонт… сумма 1 млн</think>\n" + json.dumps(ANSWER)
    provider.post("/chat/completions").respond(
        200, json=completion(content, reasoning="длинные рассуждения", reasoning_content="ещё")
    )
    parsed = parse_intent(await call(make_client()))
    assert parsed.purpose_code == "RENOVATION" and parsed.term_months == 24


async def test_extra_body_disables_reasoning(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(200, json=completion("{}"))
    await call(make_client(llm_extra_body={"reasoning": {"enabled": False}}))
    assert sent(route)["reasoning"] == {"enabled": False}


async def test_breaker_opens_after_five_failures_and_skips_provider(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(503)
    client = make_client()
    for _ in range(5):
        with pytest.raises(LlmUnavailable):
            await call(client)
    assert client.breaker.state == "open" and client.breaker.degraded
    calls = route.call_count
    with pytest.raises(LlmUnavailable, match="circuit breaker"):
        await call(client)
    assert route.call_count == calls  # к провайдеру не ходили
    # interpret при открытом breaker сразу отдаёт правила
    result = await interpret_text("нужно 2 млн на ремонт", client, 5)
    assert result.suggestion.requested_amount_rub is not None
    assert route.call_count == calls


def test_breaker_half_open_probe() -> None:
    now = [0.0]
    breaker = CircuitBreaker(threshold=5, cooldown=60, clock=lambda: now[0])
    for _ in range(5):
        breaker.record_failure()
    assert not breaker.allow()
    now[0] = 61
    assert breaker.state == "half_open"
    assert breaker.allow() and not breaker.allow()  # один пробный вызов
    breaker.record_failure()
    assert breaker.state == "open"
    now[0] = 122
    assert breaker.allow()
    breaker.record_success()
    assert breaker.state == "closed" and breaker.failures == 0


async def test_request_id_forwarded(
    provider: respx.MockRouter, make_client: Callable[..., OpenAICompatibleClient]
) -> None:
    route = provider.post("/chat/completions").respond(200, json=completion("{}"))
    token = request_id_var.set("req-123")
    try:
        await call(make_client())
    finally:
        request_id_var.reset(token)
    assert route.calls[-1].request.headers["x-request-id"] == "req-123"


async def test_logs_have_metadata_without_prompt_answer_or_key(
    provider: respx.MockRouter,
    make_client: Callable[..., OpenAICompatibleClient],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider.post("/chat/completions").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=completion(json.dumps(ANSWER)))]
    )
    with caplog.at_level(logging.INFO):
        await call(make_client())
    out = capsys.readouterr()
    logs = caplog.text + out.out + out.err
    assert "llm.call" in logs and "context_hash" in logs and "prompt_version" in logs
    for secret in (KEY, "нужно на ремонт", "RENOVATION", "client_text_untrusted"):
        assert secret not in logs, secret


async def test_not_configured_raises_unavailable(
    make_client: Callable[..., OpenAICompatibleClient],
) -> None:
    with pytest.raises(LlmUnavailable):
        await call(make_client(llm_model=None))


def test_url_validation_and_insecure_warning(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValueError, match="LLM_BASE_URL") as exc:
        make_settings(llm_base_url="ftp://user:secret@host/v1")
    assert "secret" not in str(exc.value)
    with pytest.raises(ValueError):
        make_settings(llm_base_url="not a url")
    remote = make_settings(llm_mode="openai", llm_base_url="http://llm.example.com/v1")
    assert insecure_url_warning(remote) is not None
    for local in (
        "http://localhost:11434/v1",
        "http://ollama:11434/v1",
        "http://10.0.0.5/v1",
        "http://host.docker.internal:8000/v1",
    ):
        assert insecure_url_warning(make_settings(llm_mode="openai", llm_base_url=local)) is None
    assert (
        insecure_url_warning(
            make_settings(llm_mode="openai", llm_base_url="https://llm.example.com/v1")
        )
        is None
    )


def test_factory_by_mode(make_settings: Callable[..., Settings]) -> None:
    assert build_llm_client(make_settings(llm_mode="replay")).mode == "replay"
    assert build_llm_client(make_settings(llm_mode="disabled")).mode == "disabled"
    assert build_llm_client(make_settings(llm_mode="openai", llm_base_url=BASE)).mode == "openai"


async def test_record_then_replay_roundtrip(
    provider: respx.MockRouter,
    make_client: Callable[..., OpenAICompatibleClient],
    tmp_path: Any,
) -> None:
    provider.post("/chat/completions").respond(200, json=completion(json.dumps(ANSWER)))
    recorder = RecordingClient(make_client(), tmp_path)
    recorded = await recorder.complete(LlmTask.EXTRACT_INTENT, "v1", CONTEXT, IntentLlmOutput)
    [path] = recorder.recorded
    assert path == tmp_path / "extract_intent" / "v1" / f"{recorded.context_hash}.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    assert set(fixture) == {
        "task",
        "prompt_version",
        "context_hash",
        "model",
        "provider",
        "recorded_at",
        "usage",
        "response",
    }
    assert fixture["provider"] == "llm.test" and KEY not in path.read_text(encoding="utf-8")
    replayed = await ReplayClient(tmp_path).complete(
        LlmTask.EXTRACT_INTENT, "v1", CONTEXT, IntentLlmOutput
    )
    assert replayed.content == recorded.content and replayed.model_id == "vendor/model-7b"
    original_bytes = path.read_bytes()
    # Повторная запись сохраняет ценный ответ, даже если провайдер теперь недоступен.
    provider.post("/chat/completions").respond(503)
    again = await recorder.complete(LlmTask.EXTRACT_INTENT, "v1", CONTEXT, IntentLlmOutput)
    assert again.content == recorded.content and path.read_bytes() == original_bytes
