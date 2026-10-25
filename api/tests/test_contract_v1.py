"""Регрессии контракта #6: wire-схемы, безопасность и согласованность примеров."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.core.config import Settings
from app.main import CONTRACT_ROUTERS as ROUTERS
from app.main import create_app
from app.schemas.client import InterpretResponse
from app.schemas.common import ERROR_STATUS, ErrorCode, ErrorEnvelope
from app.schemas.manager import (
    DecisionRequest,
    ExternalSource,
    ManagerApplicationView,
    OfferPreviewResponse,
)
from tests.conftest import REPO_ROOT, ext_sim_examples
from tests.test_contract import APP_ID, ENDPOINTS

PUBLIC = {"/auth/login", "/auth/demo-accounts", "/consents/texts", "/health"}
CARD_PATH = "/api/v1/manager/applications/{application_id}"
DECISIONS = f"/api/v1/manager/applications/{APP_ID}/decisions"


@pytest.fixture
def app(
    make_settings: Callable[..., Settings], db_reset: None, running: Callable[[Any], Any]
) -> FastAPI:
    app: FastAPI = running(create_app(make_settings(demo_auth_enabled=True)))
    return app


def test_bearer_security_matches_route_boundary(app: FastAPI) -> None:
    spec = app.openapi()
    assert spec["components"]["securitySchemes"]["BearerAuth"]["type"] == "http"
    assert spec["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    assert spec["components"]["securitySchemes"]["BearerAuth"]["bearerFormat"] == "JWT"
    for path, operations in spec["paths"].items():
        for operation in operations.values():
            if path.removeprefix("/api/v1") in PUBLIC:
                assert not operation.get("security"), path
            else:
                assert operation["security"] == [{"BearerAuth": []}], path


@pytest.mark.parametrize(
    ("method", "path", "body", "headers"),
    [endpoint for endpoint in ENDPOINTS if endpoint[1] not in PUBLIC],
)
def test_protected_routes_require_bearer(
    app: FastAPI, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]
) -> None:
    response = TestClient(app).request(method, "/api/v1" + path, json=body, headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize("authorization", ["Basic abc", "Bearer", "garbage"])
def test_malformed_bearer_uses_error_envelope(app: FastAPI, authorization: str) -> None:
    response = TestClient(app).get("/api/v1/auth/me", headers={"Authorization": authorization})
    assert response.status_code == 401
    ErrorEnvelope.model_validate(response.json())


@pytest.mark.parametrize("path", ["/auth/demo-accounts", "/consents/texts"])
def test_public_routes_work_without_bearer(app: FastAPI, path: str) -> None:
    assert TestClient(app).get("/api/v1" + path).status_code == 200


def test_demo_accounts_disabled_without_flag(make_settings: Callable[..., Settings]) -> None:
    client = TestClient(create_app(make_settings(demo_auth_enabled=False)))
    assert client.get("/api/v1/auth/demo-accounts").status_code == 404


# demo_code только в демо-режиме — tests/applications/test_contracts.py (реализация #7).


def test_sign_challenge_openapi_example_is_fixed(app: FastAPI) -> None:
    """Runtime-время не попадает в контракт: пример в OpenAPI детерминирован."""
    op = app.openapi()["paths"]["/api/v1/applications/{application_id}/sign/challenge"]["post"]
    example = op["responses"]["200"]["content"]["application/json"]["example"]
    assert example["expires_at"] == "2026-10-21T09:05:00Z"


VALID_DECISIONS = [
    {"action": "APPROVE", "comment": "Обосновываю одобрение"},
    {"action": "REQUEST_INFO", "question_text": "Подтвердите стоимость"},
    {"action": "REJECT", "client_reason_code": "HIGH_DEBT_LOAD", "comment": "Высокая нагрузка"},
    {
        "action": "COUNTER_OFFER",
        "client_reason_code": "HIGH_DEBT_LOAD",
        "comment": "Уменьшаем сумму",
        "amount_rub": 2340000,
    },
    {
        "action": "COUNTER_OFFER",
        "client_reason_code": "HIGH_DEBT_LOAD",
        "comment": "Меняем срок",
        "term_months": 48,
    },
    {
        "action": "COUNTER_OFFER",
        "client_reason_code": "HIGH_DEBT_LOAD",
        "comment": "Меняем условия",
        "amount_rub": 2820000,
        "term_months": 48,
    },
]


# Схема тела решения; исходы на живой БД — tests/applications/test_manager.py.
DECISION_ADAPTER: TypeAdapter[Any] = TypeAdapter(DecisionRequest)


@pytest.mark.parametrize("body", VALID_DECISIONS)
def test_action_specific_decisions_accepted(body: dict[str, Any]) -> None:
    decision = DECISION_ADAPTER.validate_python({"revision": 2, **body})
    assert decision.action == body["action"]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "REJECT"},
        {"action": "REJECT", "comment": "Отказываем"},
        {"action": "REJECT", "client_reason_code": "LOW_SCORE", "comment": "   "},
        {"action": "REQUEST_INFO"},
        {"action": "REQUEST_INFO", "question_text": " "},
        {"action": "REQUEST_INFO", "question_text": "x" * 1001},
        {"action": "COUNTER_OFFER", "amount_rub": 2340000},
        {"action": "COUNTER_OFFER", "comment": "x", "client_reason_code": "HIGH_DEBT_LOAD"},
        {
            "action": "COUNTER_OFFER",
            "comment": "x",
            "client_reason_code": "HIGH_DEBT_LOAD",
            "amount_rub": None,
            "term_months": None,
        },
        {
            "action": "COUNTER_OFFER",
            "comment": "x",
            "client_reason_code": "HIGH_DEBT_LOAD",
            "amount_rub": 0,
        },
        {"action": "APPROVE", "amount_rub": 100000},
        {"action": "REQUEST_INFO", "question_text": "x", "amount_rub": 100000},
        {"action": "UNKNOWN"},
    ],
)
def test_invalid_decisions_rejected(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DECISION_ADAPTER.validate_python({"revision": 2, **body})


def test_decision_openapi_expresses_conditions(app: FastAPI) -> None:
    spec = app.openapi()
    body = spec["paths"][CARD_PATH + "/decisions"]["post"]["requestBody"]["content"][
        "application/json"
    ]
    schema = body["schema"]
    assert len(schema["oneOf"]) == 4
    assert schema["discriminator"]["propertyName"] == "action"
    components = spec["components"]["schemas"]
    assert {"comment", "client_reason_code"} <= set(components["RejectDecision"]["required"])
    assert "question_text" in components["RequestInfoDecision"]["required"]
    counter = components["CounterOfferDecision"]
    assert {"comment", "client_reason_code"} <= set(counter["required"])
    assert {tuple(case["required"]) for case in counter["anyOf"]} == {
        ("amount_rub",),
        ("term_months",),
    }
    # В APPROVE необходимость комментария зависит от сохранённого proposal, не от action.
    TypeAdapter(DecisionRequest).validate_python({"action": "APPROVE", "revision": 2})
    assert (
        "suggested_action" in components["ApproveDecision"]["properties"]["comment"]["description"]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose_code", "NOT_A_PURPOSE"),
        ("purpose_code", 123),
        ("requested_amount_rub", "3000000"),
        ("requested_amount_rub", True),
        ("requested_amount_rub", 1.5),
        ("requested_amount_rub", 0),
        ("term_months", "36"),
        ("term_months", False),
        ("term_months", 0),
        ("term_months", 121),
    ],
)
def test_interpret_field_types_are_enforced(field: str, value: Any) -> None:
    with pytest.raises(ValidationError):
        InterpretResponse.model_validate(
            {
                "status": "OK",
                "suggestion": {field: {"value": value, "source": "RULES"}},
                "clarification_question": None,
            }
        )


def test_interpret_source_and_keys_are_constrained() -> None:
    for suggestion in [
        {"purpose_code": {"value": "EQUIPMENT", "source": "MANUAL"}},
        {"product_id": {"value": "investment", "source": "LLM"}},
    ]:
        with pytest.raises(ValidationError):
            InterpretResponse.model_validate(
                {"status": "OK", "suggestion": suggestion, "clarification_question": None}
            )
    InterpretResponse.model_validate(
        {
            "status": "OK",
            "clarification_question": None,
            "suggestion": {
                "purpose_code": {"value": "EQUIPMENT", "source": "LLM"},
                "requested_amount_rub": {"value": 3000000, "source": "RULES"},
                "term_months": {"value": 36, "source": "RULES"},
            },
        }
    )


def test_external_summary_preserves_real_json_types() -> None:
    for name, summary in ext_sim_examples().items():
        provider = {
            "EgrulCompany": "EGRUL",
            "EgripEntrepreneur": "EGRIP",
            "FnsCompanyStatus": "FNS",
            "BkiReport": "BKI",
            "BankStatement": "BANK",
        }.get(name)
        if provider is None:
            continue
        result = ExternalSource.model_validate(
            {"provider": provider, "fetched_at": "2026-10-21T09:00:00Z", "summary": summary}
        )
        assert result.model_dump(mode="json")["summary"] == summary


def test_manager_enums_and_history_examples(app: FastAPI) -> None:
    spec = app.openapi()
    schema = spec["components"]["schemas"]["ManagerApplicationView"]
    assert {
        "decisions",
        "offers",
        "info_requests",
        "contract",
        "sign_challenges",
        "timeline",
        "ai_report",
    } <= schema["properties"].keys()
    values = spec["paths"][CARD_PATH]["get"]["responses"]["200"]["content"]["application/json"][
        "examples"
    ]
    for example in values.values():
        ManagerApplicationView.model_validate(example["value"])
    issued = values["issued"]["value"]
    assert all(
        issued[field]
        for field in ["decisions", "offers", "info_requests", "sign_challenges", "timeline"]
    )
    assert issued["contract"]["signed_by_user_id"]
    assert issued["offers"][0]["scoring"]["kind"] == "COUNTER_OFFER"
    assert "code_hash" not in json.dumps(issued)
    for field, value in [
        ("purpose_code", "bad"),
        ("terms_source", "bad"),
        ("terms_field_sources", {"unknown": "RULES"}),
        ("terms_field_sources", {"purpose_code": "unknown"}),
    ]:
        with pytest.raises(ValidationError):
            ManagerApplicationView.model_validate({**values["under_review"]["value"], field: value})


def test_preview_examples_cover_invalid_and_skipped(app: FastAPI) -> None:
    content = app.openapi()["paths"][CARD_PATH + "/offer-preview"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]
    assert content["schema"]["discriminator"]["propertyName"] == "calculation_status"
    for name, example in content["examples"].items():
        result = TypeAdapter(OfferPreviewResponse).validate_python(example["value"])
        assert result.valid == (name == "valid")
        if name == "skipped":
            assert result.dscr is result.monthly_payment_rub is result.score is None
        elif name == "above_limit":
            assert result.dscr == "1.10"
            assert result.violations
    skipped = content["examples"]["skipped"]["value"]
    updates: list[dict[str, Any]] = [{"dscr": "1.25"}, {"valid": True}, {"violations": []}]
    for update in updates:
        with pytest.raises(ValidationError):
            TypeAdapter(OfferPreviewResponse).validate_python({**skipped, **update})


def test_ai_mutations_have_independent_concurrency_contract(app: FastAPI) -> None:
    paths = app.openapi()["paths"]
    regen = paths[CARD_PATH + "/ai-report"]["post"]
    assert "requestBody" not in regen
    assert "generation_id" in regen["description"]
    assert "revision" in regen["description"]
    feedback = paths[CARD_PATH + "/ai-feedback"]["post"]
    assert "revision" in feedback["description"]
    schemas = app.openapi()["components"]["schemas"]
    assert "revision" not in schemas["AiFeedbackRequest"]["properties"]
    assert "scoring_result_id" in schemas["AiReportView"]["required"]
    assert "REVISION_CONFLICT" not in json.dumps(regen["responses"])
    assert "409" not in feedback["responses"]


def test_error_examples_match_status_and_schema(app: FastAPI) -> None:
    count = 0
    for path, operations in app.openapi()["paths"].items():
        if path.endswith("/health"):
            continue
        for operation in operations.values():
            for status, response in operation["responses"].items():
                if int(status) < 400:
                    continue
                for example in response["content"]["application/json"]["examples"].values():
                    result = ErrorEnvelope.model_validate(example["value"])
                    assert ERROR_STATUS[result.error.code] == int(status)
                    if result.error.code is ErrorCode.VALIDATION_ERROR:
                        assert result.error.details
                    count += 1
    assert count > 100


def test_all_success_examples_validate_after_openapi_serialization(app: FastAPI) -> None:
    spec = json.loads(json.dumps(app.openapi()))
    for router in ROUTERS:
        for route in router.routes:
            if not isinstance(route, APIRoute) or route.status_code == 204:
                continue
            adapter = TypeAdapter(route.response_model)
            for method in route.methods or ():
                operation = spec["paths"]["/api/v1" + route.path][method.lower()]
                response = operation["responses"][str(route.status_code or 200)]
                content = response["content"]["application/json"]
                examples = content.get("examples", {"default": {"value": content.get("example")}})
                for example in examples.values():
                    adapter.validate_python(example["value"])


def test_financial_examples_balance_and_match_c2() -> None:
    from uuid import UUID

    from app.api.stubs import _build_contract, _build_manager_card

    contract = _build_contract()
    rows = contract.schedule
    assert len(rows) == contract.term_months == 36
    assert rows[0].interest_rub == "46800.00"
    balance = Decimal(contract.amount_rub)
    for row in rows:
        assert Decimal(row.payment_rub) == Decimal(row.principal_rub) + Decimal(row.interest_rub)
        balance -= Decimal(row.principal_rub)
        assert balance == Decimal(row.balance_after_rub)
    assert balance == 0
    assert sum(Decimal(r.interest_rub) for r in rows) == Decimal(contract.overpayment_rub)
    scoring = _build_manager_card(UUID(APP_ID)).model_dump(mode="json")["scoring"]
    assert len(scoring["monthly"]) == 12
    assert sum(scoring["factor_points"].values()) == scoring["score"] == 63
    assert scoring["dscr"] == "1.10"
    assert scoring["limit_rub"] == "2340000.00"
    monthly = scoring["monthly"]
    before = sum(Decimal(m["revenue_rub"]) for m in monthly[:6])
    after = sum(Decimal(m["revenue_rub"]) for m in monthly[6:])
    assert (after / before - 1) * 100 == Decimal("-8")


def test_openapi_export_is_deterministic_and_current(tmp_path: Path) -> None:
    outputs = []
    for seed in ["1", "43"]:
        output = tmp_path / f"openapi-{seed}.json"
        env = {
            **os.environ,
            "PYTHONHASHSEED": seed,
            "APP_ENV": "local",
            "TEST_RESET_ENABLED": "false",
            "LOAD_TEST_ENABLED": "false",
        }
        subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts/export_openapi.py"),
                "app.main:app",
                str(output),
            ],
            cwd=REPO_ROOT / "api",
            env=env,
            check=True,
            capture_output=True,
            timeout=30,
        )
        outputs.append(output.read_bytes())
    assert outputs[0] == outputs[1] == (REPO_ROOT / "docs/openapi.json").read_bytes()
