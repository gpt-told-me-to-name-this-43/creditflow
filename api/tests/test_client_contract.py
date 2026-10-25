"""Сценарии #9, которые фронт должен выполнять только по данным контракта."""

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.openapi.models import OpenAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import AppError, install_error_handlers
from app.main import create_app
from app.schemas.common import ErrorCode
from app.schemas.enums import ApplicationStatus
from tests.conftest import REPO_ROOT

BASE = "/api/v1/applications/{application_id}"


@pytest.fixture
def app(make_settings: Callable[..., Settings]) -> FastAPI:
    return create_app(make_settings(demo_auth_enabled=True))


def test_client_scenarios_are_consistent(app: FastAPI) -> None:
    cases = app.openapi()["paths"][BASE]["get"]["responses"]["200"]["content"]["application/json"][
        "examples"
    ]
    assert {s.value for s in ApplicationStatus} == {e["value"]["status"] for e in cases.values()}
    for example in cases.values():
        value = example["value"]
        assert value["timeline"][-1]["to_status"] == value["status"]
        status = None
        for event in value["timeline"]:
            assert event["from_status"] == status
            status = event["to_status"]
        if value["status"] in {"UNDER_REVIEW", "REJECTED", "DECLINED"}:
            assert value["allowed_actions"] == []
        if value["status"] == "COUNTER_OFFER":
            assert set(value["allowed_actions"]) == {"ACCEPT_OFFER", "DECLINE_OFFER"}
            assert value["offer"]
        if value["status"] == "NEED_INFO":
            assert value["info_request"]["question_text"]
            assert value["allowed_actions"] == ["RESPOND_INFO"]
    extended = cases["counter_offer_term"]["value"]
    offer = extended["offer"]
    # M11: 48 мес. для 3 млн превышали бы лимит; минимальный срок — 54.
    assert offer["term_months"] == 54
    assert offer["monthly_payment_rub"] == "91356.79"
    assert offer["amount_rub"] == extended["requested_amount_rub"]
    assert offer["term_months"] > extended["term_months"]
    assert Decimal(offer["monthly_payment_rub"]) < Decimal(extended["monthly_payment_rub"])
    assert Decimal(offer["overpayment_rub"]) > Decimal(extended["overpayment_rub"])


# Новый черновик без сохранения подсказок — tests/applications/test_drafts.py (реализация #7).


# revision из challenge в sign — tests/applications/test_contracts.py (реализация #7).


def test_sign_errors_deliver_attempts_and_retry_header() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/sign")
    async def sign() -> None:
        raise AppError(
            ErrorCode.TOO_MANY_ATTEMPTS,
            "Повторите позже",
            details={"scope": "CHALLENGE_ISSUE", "retry_after_seconds": 60},
            headers={"Retry-After": "60"},
        )

    response = TestClient(app).post("/sign")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "60"
    assert response.json()["error"]["details"] == {
        "scope": "CHALLENGE_ISSUE",
        "retry_after_seconds": 60,
    }


def test_export_has_valid_structure_and_resolvable_references() -> None:
    spec = json.loads((REPO_ROOT / "docs/openapi.json").read_text())
    OpenAPI.model_validate(spec)

    def check(value: Any) -> None:
        if isinstance(value, list):
            for item in value:
                check(item)
        elif isinstance(value, dict):
            if "$ref" in value:
                ref = value["$ref"]
                assert ref.startswith("#/"), ref
                resolved = spec
                for part in ref[2:].split("/"):
                    resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
            for item in value.values():
                check(item)

    check(spec)
