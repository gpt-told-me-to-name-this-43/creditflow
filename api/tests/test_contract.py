"""Контракт API v1 (issue #6): полнота маршрутов, стабы проходят response_model,
в клиентских схемах нет внутренних полей, деньги — строки, ошибки — ErrorEnvelope."""

import inspect
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.main import create_app
from app.schemas import client as client_schemas
from app.schemas.common import ErrorCode

APP_ID = "7f3e2a10-0000-4000-8000-000000000001"
IDEM = {"Idempotency-Key": "test-key-0001"}

# (method, path, body, headers) — ровно таблица эндпоинтов #6 (кроме /health и /_test/reset).
ENDPOINTS: list[tuple[str, str, dict[str, Any] | None, dict[str, str]]] = [
    ("POST", "/auth/login", {"login": "a", "password": "b"}, {}),
    ("GET", "/auth/me", None, {}),
    ("GET", "/auth/demo-accounts", None, {}),
    ("GET", "/consents/texts", None, {}),
    (
        "POST",
        "/onboarding/company-binding",
        {"inn": "0099020010", "pd_consent_version": "pd-v1"},
        {},
    ),
    ("GET", "/company", None, {}),
    ("GET", "/credit-products", None, {}),
    ("POST", "/applications", {}, {}),
    ("GET", "/applications", None, {}),
    ("GET", f"/applications/{APP_ID}", None, {}),
    ("PATCH", f"/applications/{APP_ID}", {"revision": 1, "term_months": 36}, {}),
    ("POST", f"/applications/{APP_ID}/interpret", {"purpose_text": "печь за 3 млн"}, {}),
    (
        "POST",
        f"/applications/{APP_ID}/submit",
        {"revision": 1, "bki_consent_version": "bki-v1"},
        IDEM,
    ),
    ("POST", f"/applications/{APP_ID}/info-response", {"revision": 1, "answer_text": "ok"}, IDEM),
    ("POST", f"/applications/{APP_ID}/offer/accept", {"revision": 1}, IDEM),
    ("POST", f"/applications/{APP_ID}/offer/decline", {"revision": 1}, IDEM),
    ("GET", f"/applications/{APP_ID}/contract", None, {}),
    ("POST", f"/applications/{APP_ID}/sign/challenge", {"revision": 1}, {}),
    (
        "POST",
        f"/applications/{APP_ID}/sign",
        {"revision": 1, "challenge_id": APP_ID, "code": "123456"},
        IDEM,
    ),
    ("GET", "/manager/applications", None, {}),
    ("GET", f"/manager/applications/{APP_ID}", None, {}),
    (
        "POST",
        f"/manager/applications/{APP_ID}/decisions",
        {"revision": 2, "action": "APPROVE", "comment": "ok"},
        IDEM,
    ),
    (
        "POST",
        f"/manager/applications/{APP_ID}/offer-preview",
        {"amount_rub": 2340000, "term_months": 36},
        {},
    ),
    ("GET", f"/manager/applications/{APP_ID}/ai-report", None, {}),
    ("POST", f"/manager/applications/{APP_ID}/ai-report", None, {}),
    (
        "POST",
        f"/manager/applications/{APP_ID}/ai-feedback",
        {"ai_report_id": APP_ID, "verdict": "UP"},
        {},
    ),
    ("GET", "/manager/stats", None, {}),
]

FORBIDDEN_CLIENT_FIELDS = re.compile(
    r"score|dscr|limit|reason_codes|positive_codes|blocking|suggested|rule_trace|ai_|comment|risk"
)


@pytest.fixture
def app(make_settings: Callable[..., Settings]) -> FastAPI:
    return create_app(make_settings())


def _template(path: str) -> str:
    return re.sub(r"[0-9a-f-]{36}", "{application_id}", path)


def test_all_contract_routes_registered(app: FastAPI) -> None:
    # Сверяем по OpenAPI — именно его видит фронт. app.routes в FastAPI 0.159 хранит
    # подключённые роутеры как вложенные _IncludedRouter, а не плоский список маршрутов.
    paths = app.openapi()["paths"]
    declared = {(m.upper(), path) for path, ops in paths.items() for m in ops}
    expected = {(m, "/api/v1" + _template(p)) for m, p, _, _ in ENDPOINTS}
    assert expected <= declared, sorted(expected - declared)


@pytest.mark.parametrize(("method", "path", "body", "headers"), ENDPOINTS, ids=lambda v: str(v))
def test_stub_passes_response_model(
    app: FastAPI, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]
) -> None:
    # TestClient без контекстного менеджера: lifespan (БД, ext-sim) стабам не нужен.
    response = TestClient(app).request(method, "/api/v1" + path, json=body, headers=headers)
    assert response.status_code < 300, response.text  # response_model валидирует ответ стаба


def test_idempotency_key_is_required(app: FastAPI) -> None:
    r = TestClient(app).post(
        f"/api/v1/applications/{APP_ID}/submit",
        json={"revision": 1, "bki_consent_version": "bki-v1"},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_errors_use_envelope(app: FastAPI) -> None:
    client = TestClient(app)
    assert (
        client.get("/api/v1/applications/not-a-uuid").json()["error"]["code"] == "VALIDATION_ERROR"
    )
    assert client.get("/api/v1/nope").json() == {
        "error": {"code": "NOT_FOUND", "message": "Not Found"}
    }


def test_client_schemas_have_no_internal_fields() -> None:
    models = [
        m
        for _, m in inspect.getmembers(client_schemas, inspect.isclass)
        if issubclass(m, BaseModel) and m.__module__ == client_schemas.__name__
    ]
    leaked = {
        f"{m.__name__}.{f}"
        for m in models
        for f in m.model_fields
        if FORBIDDEN_CLIENT_FIELDS.search(f)
    }
    assert not leaked


def test_money_is_never_a_number(app: FastAPI) -> None:
    schemas = app.openapi()["components"]["schemas"]
    for name, schema in schemas.items():
        for field, prop in schema.get("properties", {}).items():
            if field.endswith("_rub") or field in {"dscr"}:
                types = {prop.get("type")} | {s.get("type") for s in prop.get("anyOf", [])}
                assert "number" not in types, f"{name}.{field}"


def test_error_codes_documented() -> None:
    doc = (Path(__file__).resolve().parents[2] / "docs" / "api.md").read_text(encoding="utf-8")
    missing = [c.value for c in ErrorCode if f"`{c.value}`" not in doc]
    assert not missing
