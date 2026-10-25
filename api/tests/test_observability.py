"""Логи, request id, маскирование и защитные заголовки `api` (#5)."""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logs import MASK, configure_logging, get_logger, mask_sensitive
from app.core.middleware import resolve_request_id
from app.core.request_context import request_id_var
from app.extsim_client import ExtSimClient
from app.main import create_app
from app.seed import DEMO_PASSWORD
from tests.conftest import CLIENT_LOGIN, EXT_SIM_URL, bearer
from tests.test_onboarding import BAKERY_DIRECTOR, BAKERY_INN, registry

LLM_KEY = "sk-llm-secret-key-should-never-be-logged"


@pytest.fixture
def app(
    make_settings: Callable[..., Settings], db_reset: None, running: Callable[[Any], Any]
) -> FastAPI:
    app: FastAPI = running(create_app(make_settings(llm_api_key=LLM_KEY)))
    return app


def log_lines(output: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in output.splitlines() if line.startswith("{")]


# --- Маскирование ----------------------------------------------------------------------


def test_mask_nested_structures() -> None:
    event = {
        "event": "x",
        "password": "p",
        "Authorization": "Bearer t",
        "nested": {
            "access_token": "t",
            "items": [{"purpose_text": "печь", "ok": 1}, ("comment", {"answer_text": "a"})],
            "llm": {"API_KEY": "k", "messages": [{"role": "user", "content": "c"}]},
        },
        "x-test-reset-token": "r",
        "status": 200,
    }
    assert mask_sensitive(None, "info", event) == {
        "event": "x",
        "password": MASK,
        "Authorization": MASK,
        "nested": {
            "access_token": MASK,
            "items": [{"purpose_text": MASK, "ok": 1}, ["comment", {"answer_text": MASK}]],
            "llm": {"API_KEY": MASK, "messages": MASK},
        },
        "x-test-reset-token": MASK,
        "status": 200,
    }


def test_secrets_never_reach_logs(app: FastAPI, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()  # обработчик пишет в sys.stdout, перехваченный capsys
    client = TestClient(app)
    token = client.post(
        "/api/v1/auth/login", json={"login": CLIENT_LOGIN, "password": DEMO_PASSWORD}
    ).json()["access_token"]
    client.post("/api/v1/auth/login", json={"login": CLIENT_LOGIN, "password": "wrong-pass-1"})
    client.post("/api/v1/auth/login", json={"login": CLIENT_LOGIN})  # 422 без тела в логе
    client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    client.get("/api/v1/auth/me", headers={"Authorization": "Bearer forged.token.value"})
    get_logger("app.test").info(
        "llm call", api_key=LLM_KEY, messages=[{"content": "Купить печь"}], password="x"
    )
    output = capsys.readouterr().out
    assert log_lines(output), "логи не JSON"
    for secret in (DEMO_PASSWORD, "wrong-pass-1", token, "forged.token.value", LLM_KEY):
        assert secret not in output
    assert "Купить печь" not in output


def test_access_log_fields(app: FastAPI, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    TestClient(app).get(
        "/api/v1/auth/me?x=secret-query",
        headers={**bearer(CLIENT_LOGIN), "X-Request-ID": "trace-0001"},
    )
    lines = [line for line in log_lines(capsys.readouterr().out) if line["event"] == "request"]
    assert len(lines) == 1
    line = lines[0]
    assert {
        "ts",
        "level",
        "request_id",
        "user_id",
        "role",
        "method",
        "path",
        "status",
        "duration_ms",
    } <= set(line)
    assert line["request_id"] == "trace-0001"
    assert line["role"] == "CLIENT"
    assert line["method"] == "GET"
    assert line["path"] == "/api/v1/auth/me"  # без query
    assert line["status"] == 200
    assert line["level"] == "info"


# --- Request id ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [
        ("abc-123", True),
        ("0f8fad5b-d9cb-469f-a165-70867728950e", True),
        ("a" * 128, True),
        ("a" * 129, False),
        ("bad id", False),
        ("evil\r\nX-Injected: 1", False),
        ("ид-кириллица", False),
        ("", False),
        (None, False),
    ],
)
def test_request_id_validation(incoming: str | None, kept: bool) -> None:
    resolved = resolve_request_id(incoming)
    assert (resolved == incoming) is kept
    assert 1 <= len(resolved) <= 128


def test_request_id_round_trip(app: FastAPI) -> None:
    client = TestClient(app)
    assert (
        client.get("/api/v1/consents/texts", headers={"X-Request-ID": "rid-1"}).headers[
            "X-Request-ID"
        ]
        == "rid-1"
    )
    generated = client.get("/api/v1/consents/texts", headers={"X-Request-ID": "bad id"})
    assert generated.headers["X-Request-ID"] not in ("bad id", "")


async def test_ext_sim_gets_request_id_by_default() -> None:
    with respx.mock(base_url=EXT_SIM_URL) as sim:
        route = sim.get(f"/egrul/v1/companies/{BAKERY_INN}").respond(200, json=registry(BAKERY_INN))
        async with ExtSimClient(EXT_SIM_URL) as client:
            token = request_id_var.set("rid-from-api")
            try:
                await client.get_registry_record(BAKERY_INN)
                await client.get_registry_record(BAKERY_INN, request_id="explicit")
            finally:
                request_id_var.reset(token)
            await client.get_registry_record(BAKERY_INN)
    sent = [call.request.headers.get("X-Request-ID") for call in route.calls]
    assert sent == ["rid-from-api", "explicit", None]


async def test_binding_passes_request_id_to_ext_sim(
    make_settings: Callable[..., Settings],
    db_reset: None,
    serve: Callable[[Any], Any],
) -> None:
    with respx.mock(base_url=EXT_SIM_URL) as sim:
        route = sim.get(f"/egrul/v1/companies/{BAKERY_INN}").respond(200, json=registry(BAKERY_INN))
        api: httpx.AsyncClient = await serve(create_app(make_settings()))
        response = await api.post(
            "/api/v1/onboarding/company-binding",
            json={"inn": BAKERY_INN, "pd_consent_version": "pd-v1"},
            headers={**bearer(BAKERY_DIRECTOR), "X-Request-ID": "trace-ext-sim"},
        )
    assert response.status_code == 200
    assert route.calls.last.request.headers["X-Request-ID"] == "trace-ext-sim"


# --- Защитные заголовки ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/consents/texts"),
        ("GET", "/api/v1/auth/me"),  # 401
        ("GET", "/api/v1/nope"),  # 404
        ("POST", "/api/v1/auth/login"),  # 422
    ],
)
def test_security_headers(app: FastAPI, method: str, path: str) -> None:
    response = TestClient(app).request(method, path, json={})
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"
    assert "X-Request-ID" in response.headers


def test_unhandled_error_has_envelope_and_headers(
    make_settings: Callable[..., Settings], capsys: pytest.CaptureFixture[str]
) -> None:
    app = create_app(make_settings())
    configure_logging()

    @app.get("/api/v1/_boom")
    async def boom() -> None:
        raise RuntimeError("password=hunter2 внутри исключения")

    response = TestClient(app).get("/api/v1/_boom", headers={"X-Request-ID": "rid-500"})
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервера"}
    }
    assert "hunter2" not in response.text
    assert response.headers["X-Request-ID"] == "rid-500"
    assert response.headers["Cache-Control"] == "no-store"
    error = [line for line in log_lines(capsys.readouterr().out) if line["event"] != "request"]
    assert error and error[0]["request_id"] == "rid-500"
