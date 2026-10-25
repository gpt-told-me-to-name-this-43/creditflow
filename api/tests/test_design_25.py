"""Design 2.5: декларации отдельно от runtime обработчиков и валидации DTO.

Здесь не проверяется несуществующая пока FSM, OTP, rate limit или запуск AI.
"""

import subprocess
import sys
from typing import Annotated, Any
from uuid import UUID

import pytest
from fastapi import FastAPI, Header, Query
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.examples import REQUEST_EXAMPLES
from app.api.stubs import _build_manager_card
from app.core.errors import AppError, install_error_handlers
from app.schemas.client import ApplicationCreate, ApplicationPatch, InterpretRequest
from app.schemas.common import (
    ERROR_STATUS,
    ApplicationIncompleteDetails,
    ErrorBody,
    ErrorCode,
    ErrorEnvelope,
    ProductConstraint,
    ProductNotEligibleDetails,
    RevisionConflictDetails,
    Schema,
    SignCodeInvalidDetails,
    TooManyAttemptsDetails,
)
from app.schemas.enums import ManagerAction
from app.schemas.manager import ManagerApplicationView, OfferConstraints
from tests.conftest import REPO_ROOT
from tests.test_contract import APP_ID


class Item(Schema):
    code: int


class Items(Schema):
    items: list[Item]


@pytest.mark.parametrize(
    ("method", "path", "body", "headers", "expected"),
    [
        ("POST", "/items", {"items": [{"code": "invalid"}]}, {}, "body.items.0.code"),
        ("GET", "/query?amount=0", None, {}, "query.amount"),
        ("GET", "/path/not-a-uuid", None, {}, "path.application_id"),
        ("GET", "/header", None, {}, "header.Idempotency-Key"),
        ("GET", "/header", None, {"Idempotency-Key": "x"}, "header.Idempotency-Key"),
    ],
)
def test_validation_paths(
    method: str, path: str, body: Any, headers: dict[str, str], expected: str
) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/items")
    async def items(body: Items) -> None:
        pass

    @app.get("/query")
    async def query(amount: Annotated[int, Query(gt=0)]) -> None:
        pass

    @app.get("/path/{application_id}")
    async def path_parameter(application_id: UUID) -> None:
        pass

    @app.get("/header")
    async def header(key: Annotated[str, Header(alias="Idempotency-Key", min_length=8)]) -> None:
        pass

    response = TestClient(app).request(method, path, json=body, headers=headers)
    assert response.status_code == 422
    value = response.json()
    ErrorEnvelope.model_validate(value)
    fields = value["error"]["details"]["fields"]
    assert fields[0]["field"] == expected
    assert set(fields[0]) == {"field", "code", "message"}
    if expected == "query.amount":
        assert fields[0]["code"] == "OUT_OF_RANGE"


@pytest.mark.parametrize("model", [ApplicationCreate, ApplicationPatch, InterpretRequest])
def test_purpose_text_limit(model: Any) -> None:
    example = REQUEST_EXAMPLES[model]
    model.model_validate({**example, "purpose_text": "я" * 1000})
    with pytest.raises(ValidationError):
        model.model_validate({**example, "purpose_text": "я" * 1001})


@pytest.mark.parametrize(
    ("code", "details", "model"),
    [
        (
            ErrorCode.APPLICATION_INCOMPLETE,
            {"missing_fields": ["product_id"]},
            ApplicationIncompleteDetails,
        ),
        (
            ErrorCode.PRODUCT_NOT_ELIGIBLE,
            {"product_id": "investment", "unmet_constraints": ["AMOUNT_BELOW_PRODUCT_MIN"]},
            ProductNotEligibleDetails,
        ),
        (ErrorCode.REVISION_CONFLICT, {"current_revision": 8}, RevisionConflictDetails),
        (ErrorCode.SIGN_CODE_INVALID, {"remaining_attempts": 2}, SignCodeInvalidDetails),
        (ErrorCode.TOO_MANY_ATTEMPTS, {"scope": "SIGN_ATTEMPTS"}, TooManyAttemptsDetails),
    ],
)
def test_canonical_domain_details_runtime(
    code: ErrorCode, details: dict[str, Any], model: Any
) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/error")
    async def fail() -> None:
        raise AppError(code, "Ошибка", details=details, headers={"Retry-After": "60"})

    response = TestClient(app).get("/error")
    assert response.status_code == ERROR_STATUS[code]
    assert response.json()["error"]["details"] == details
    assert isinstance(ErrorEnvelope.model_validate(response.json()).error.details, model)
    if details.get("scope") == "SIGN_ATTEMPTS":
        assert "Retry-After" not in response.headers


def test_old_details_array_and_mismatched_details_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ErrorBody.model_validate({"code": "VALIDATION_ERROR", "message": "x", "details": []})
    with pytest.raises(ValidationError):
        ErrorBody.model_validate(
            {"code": "REVISION_CONFLICT", "message": "x", "details": {"missing_fields": []}}
        )
    with pytest.raises(ValidationError):
        TooManyAttemptsDetails(scope="SIGN_ATTEMPTS", retry_after_seconds=60)


def test_product_constraint_is_canonical() -> None:
    assert {c.value for c in ProductConstraint} == {
        "PURPOSE_NOT_ALLOWED",
        "AMOUNT_BELOW_PRODUCT_MIN",
        "AMOUNT_ABOVE_PRODUCT_MAX",
        "TERM_BELOW_PRODUCT_MIN",
        "TERM_ABOVE_PRODUCT_MAX",
    }
    with pytest.raises(ValidationError):
        ProductNotEligibleDetails.model_validate(
            {
                "product_id": "investment",
                "unmet_constraints": [{"code": "AMOUNT_ABOVE_PRODUCT_MAX"}],
            }
        )


@pytest.mark.parametrize("counter_offer", [True, False])
def test_offer_constraints_action_invariant(counter_offer: bool) -> None:
    card = _build_manager_card(UUID(APP_ID)).model_dump(mode="json")
    if not counter_offer:
        card["allowed_actions"].remove("COUNTER_OFFER")
        card["offer_constraints"] = None
    ManagerApplicationView.model_validate(card)
    card["offer_constraints"] = (
        None
        if counter_offer
        else {
            "min_amount_rub": "100000.00",
            "max_amount_rub": "5000000.00",
            "min_term_months": 12,
            "max_term_months": 60,
        }
    )
    with pytest.raises(ValidationError):
        ManagerApplicationView.model_validate(card)


def test_offer_constraints_strict_required_and_money_pattern() -> None:
    card = _build_manager_card(UUID(APP_ID))
    assert ManagerAction.COUNTER_OFFER in card.allowed_actions
    constraints = card.offer_constraints
    assert constraints is not None
    value = constraints.model_dump()
    for change in ({"max_amount_rub": "-1.00"}, {"min_amount_rub": 1}, {"extra": 1}):
        with pytest.raises(ValidationError):
            OfferConstraints.model_validate({**value, **change})
    value.pop("min_amount_rub")
    with pytest.raises(ValidationError):
        OfferConstraints.model_validate(value)
    data = card.model_dump()
    data.pop("offer_constraints")
    with pytest.raises(ValidationError):
        ManagerApplicationView.model_validate(data)


def test_generated_matrix_is_current() -> None:
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/gen_api_matrix.py"), "--check"], check=True
    )


@pytest.mark.parametrize("scope", ["LOGIN", "CHALLENGE_ISSUE"])
def test_retry_after_is_integer_and_matches_details(scope: str) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/limit")
    async def limit() -> None:
        raise AppError(
            ErrorCode.TOO_MANY_ATTEMPTS,
            "Подождите",
            details={
                "scope": scope,
                "retry_after_seconds": 90,
            },
        )

    response = TestClient(app).get("/limit")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "90"


def test_ai_success_status_examples() -> None:
    from app.main import create_app

    responses = create_app().openapi()["paths"][
        "/api/v1/manager/applications/{application_id}/ai-report"
    ]["post"]["responses"]
    accepted = responses["202"]["content"]["application/json"]["example"]
    assert accepted["status"] == "PENDING" and accepted["report"] is None
    existing = responses["200"]["content"]["application/json"]["examples"]
    assert {case["value"]["status"] for case in existing.values()} == {
        "PENDING",
        "READY",
        "FALLBACK",
    }


@pytest.mark.parametrize(
    ("method", "path", "body", "field"),
    [
        # реализованные маршруты (#7) — tests/applications/; здесь оставшийся стаб
        (
            "POST",
            "/applications/" + APP_ID + "/interpret",
            {"purpose_text": "x" * 1001},
            "body.purpose_text",
        ),
    ],
)
def test_real_route_validation_uses_json_field_paths(
    method: str, path: str, body: dict[str, Any], field: str
) -> None:
    from app.main import create_app
    from tests.test_contract import AUTH, IDEM

    response = TestClient(create_app(), headers={**AUTH, **IDEM}).request(
        method, "/api/v1" + path, json=body
    )
    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"][0]["field"] == field


def test_catalog_v2_rates_match_design_and_financial_inputs() -> None:
    from decimal import Decimal

    from app.seed import CATALOG_VERSION, PRODUCTS
    from tests.scoring._data import INVESTMENT, WORKING_CAPITAL

    assert CATALOG_VERSION == "products-v2"
    assert {p["id"]: p["annual_rate_pct"] for p in PRODUCTS} == {
        "investment": Decimal(24),
        "working_capital": Decimal(25),
    }
    assert INVESTMENT.annual_rate_pct == Decimal(24)
    assert WORKING_CAPITAL.annual_rate_pct == Decimal(25)
