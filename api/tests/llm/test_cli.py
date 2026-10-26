"""Диагностика, коды выхода и защита записи CLI; без внешнего провайдера."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import respx

from app.core.config import Settings
from app.llm import cli
from app.llm.client import OpenAICompatibleClient
from tests.llm.test_client import completion


@pytest.mark.parametrize("status", [200, 401, 404, 503])
async def test_check_exit_code_and_no_provider_error_body(
    status: int,
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = make_settings(
        llm_mode="openai",
        llm_base_url="https://llm.test/v1",
        llm_model="model",
        llm_api_key="secret-token",
    )
    client = OpenAICompatibleClient(settings, http_client=httpx.AsyncClient(trust_env=False))
    monkeypatch.setattr(cli, "OpenAICompatibleClient", lambda _: client)
    with respx.mock() as provider:
        route = provider.post("https://llm.test/v1/chat/completions").respond(
            status,
            json=completion('{"answer":"ok"}')
            if status == 200
            else {"error": {"message": "secret-token private-company account-123"}},
        )
        assert await cli.check(settings) == (0 if status == 200 else 1)
        assert route.call_count == 1  # выбранный формат, без скрытых платных проб
    output = capsys.readouterr().out
    assert "secret-token" not in output and "private-company" not in output
    assert client._client.is_closed()


async def test_probe_formats_does_not_hide_broken_selected_format(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(llm_mode="openai", llm_base_url="https://llm.test/v1", llm_model="m")
    client = OpenAICompatibleClient(settings, http_client=httpx.AsyncClient(trust_env=False))
    monkeypatch.setattr(cli, "OpenAICompatibleClient", lambda _: client)
    with respx.mock() as provider:
        provider.post("https://llm.test/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "unsupported format"}}),
                httpx.Response(200, json=completion('{"answer":"ok"}')),
                httpx.Response(200, json=completion('{"answer":"ok"}')),
            ]
        )
        assert await cli.check(settings, probe_formats=True) == 1


async def test_record_requires_explicit_opt_in_and_database(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings(llm_mode="openai", llm_base_url="https://llm.test/v1", llm_model="m")
    monkeypatch.delenv("LLM_RECORD", raising=False)
    assert await cli.record(settings) == 1
    monkeypatch.setenv("LLM_RECORD", "1")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    assert await cli.record(settings) == 1
    assert await cli.scenarios(settings) == 1


async def test_rules_only_cli_threshold_fails(
    tmp_path: Path,
    make_settings: Callable[..., Settings],
) -> None:
    dataset = tmp_path / "cases.jsonl"
    dataset.write_text(
        '{"id":"x","category":"clean","text":"текст","author":"test",'
        '"expected":{"requested_amount_rub":123,"term_months":7}}\n'
    )
    assert await cli.eval_intent(make_settings(), dataset, [], None, rules_only=True) == 1


async def test_scenarios_preserve_zero_settings(
    make_settings: Callable[..., Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql+psycopg://test@localhost/test")
    process = AsyncMock()
    process.wait.return_value = 0
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr("app.llm.cli.asyncio.create_subprocess_exec", spawn)
    assert await cli.scenarios(make_settings(llm_temperature=0, llm_seed=0)) == 0
    env = spawn.call_args.kwargs["env"]
    assert env["LLM_TEMPERATURE"] == "0.0" and env["LLM_SEED"] == "0"
    assert "LLM_LIVE" not in env and "LLM_RECORD" not in env
