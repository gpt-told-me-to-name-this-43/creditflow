"""Финальное ревью PR #12: регрессионные тесты на findings 1–6."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.examples import attach_examples, check_history, example_from
from app.core.config import Settings
from app.core.errors import install_error_handlers
from app.main import create_app
from app.schemas.common import ERROR_STATUS, ErrorCode
from tests.test_contract import APP_ID, AUTH


@pytest.fixture
def app(make_settings: Callable[..., Settings]) -> FastAPI:
    return create_app(make_settings(demo_auth_enabled=True))


# --- 1. Стабы с «проверкой» только наличия Bearer не доступны в production -----------------


def test_stubs_not_mounted_in_production(make_settings: Callable[..., Settings]) -> None:
    app = create_app(make_settings(app_env="production"))
    paths = app.openapi()["paths"]
    assert set(paths) == {"/api/v1/health"}
    client = TestClient(app, headers=AUTH)
    assert client.get("/api/v1/applications").status_code == 404
    assert (
        client.post("/api/v1/auth/login", json={"login": "x", "password": "y"}).status_code == 404
    )


def test_any_bearer_is_accepted_outside_production(app: FastAPI) -> None:
    """Фиксирует честное ограничение #6: токен не проверяется (JWT и RBAC — #5)."""
    client = TestClient(app, headers={"Authorization": "Bearer not-a-jwt"})
    assert client.get("/api/v1/manager/stats").status_code == 200
    assert TestClient(app).get("/api/v1/manager/stats").status_code == 401


# --- 3. Примеры OpenAPI не исполняют endpoint --------------------------------------------


def test_examples_do_not_execute_endpoints() -> None:
    router = APIRouter()
    calls: list[str] = []

    def build() -> dict[str, str]:
        return {"ok": "example"}

    @router.get("/awaiting")
    @example_from(build)
    async def awaiting() -> dict[str, str]:
        calls.append("endpoint")
        await asyncio.sleep(0)  # обработчик с настоящим await (как будет в #5/#7)
        return build()

    attach_examples((router,))
    assert calls == []
    route = router.routes[0]
    example = route.openapi_extra["responses"]["200"]["content"]["application/json"]["example"]  # type: ignore[attr-defined]
    assert example == {"ok": "example"}


def test_route_without_example_builder_fails_loudly() -> None:
    router = APIRouter()

    @router.get("/bare")
    async def bare() -> dict[str, str]:
        return {}

    with pytest.raises(RuntimeError, match="example_from"):
        attach_examples((router,))


def test_async_example_builder_is_rejected() -> None:
    router = APIRouter()

    async def build() -> dict[str, str]:
        return {}

    @router.get("/async-builder")
    @example_from(build)
    async def handler() -> dict[str, str]:
        return {}

    with pytest.raises(TypeError, match="sync"):
        attach_examples((router,))


# --- 4. История выданной заявки C2 ------------------------------------------------------


def _card_examples(app: FastAPI) -> dict[str, Any]:
    op = app.openapi()["paths"]["/api/v1/manager/applications/{application_id}"]["get"]
    examples = op["responses"]["200"]["content"]["application/json"]["examples"]
    return {name: case["value"] for name, case in examples.items()}


def test_issued_example_preserves_requested_terms(app: FastAPI) -> None:
    issued = _card_examples(app)["issued"]
    assert issued["requested_amount_rub"] == "3000000.00"
    assert [o["amount_rub"] for o in issued["offers"]] == ["2340000.00"]
    assert issued["contract"]["amount_rub"] == "2340000.00"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda v: v.update(requested_amount_rub="2340000.00"), "requested_amount_rub"),
        (lambda v: v["contract"].update(amount_rub="2000000.00"), "договор.amount_rub"),
        (lambda v: v["timeline"].pop(2), "разрыв timeline"),
        (lambda v: v.update(status="SIGNED"), "timeline заканчивается"),
        (lambda v: v["offers"][0].update(decision_id=APP_ID), "без решения COUNTER_OFFER"),
        (lambda v: v["timeline"][0].update(created_at="2026-10-22T00:00:00Z"), "убывает"),
    ],
)
def test_history_check_catches_inconsistency(
    app: FastAPI, mutate: Callable[[dict[str, Any]], object], message: str
) -> None:
    cases = _card_examples(app)
    issued = deepcopy(cases["issued"])
    check_history(cases["under_review"], issued)  # исходный пример согласован
    mutate(issued)
    with pytest.raises(ValueError, match=message):
        check_history(cases["under_review"], issued)


# --- 5. GET /credit-products --------------------------------------------------------------


def products(app: FastAPI, **params: object) -> dict[str, dict[str, Any]]:
    response = TestClient(app, headers=AUTH).get("/api/v1/credit-products", params=params)
    assert response.status_code == 200
    return {p["id"]: p for p in response.json()}


def test_catalog_has_both_products_without_filters(app: FastAPI) -> None:
    result = products(app)
    assert set(result) == {"investment", "working_capital"}
    for p in result.values():
        assert p["suitable"] is True and p["unmet_constraints"] == []
        assert p["monthly_payment_rub"] is None  # без суммы и срока платёж не считается


def test_c2_request_matches_only_investment(app: FastAPI) -> None:
    result = products(app, purpose="EQUIPMENT", amount=3_000_000, term=36)
    assert result["investment"]["suitable"] is True
    assert result["investment"]["monthly_payment_rub"] == "117698.56"  # M1
    assert result["working_capital"]["suitable"] is False
    assert result["working_capital"]["monthly_payment_rub"] is None
    assert result["working_capital"]["unmet_constraints"] == [
        "PURPOSE_NOT_ALLOWED",
        "TERM_ABOVE_PRODUCT_MAX",
    ]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"amount": 50_000}, ["AMOUNT_BELOW_PRODUCT_MIN"]),
        ({"amount": 3_000_001, "term": 2}, ["AMOUNT_ABOVE_PRODUCT_MAX", "TERM_BELOW_PRODUCT_MIN"]),
    ],
)
def test_working_capital_bounds(app: FastAPI, params: dict[str, int], expected: list[str]) -> None:
    assert products(app, **params)["working_capital"]["unmet_constraints"] == expected


def test_openapi_example_matches_c2_query(app: FastAPI) -> None:
    op = app.openapi()["paths"]["/api/v1/credit-products"]["get"]
    example = op["responses"]["200"]["content"]["application/json"]["example"]
    assert example == list(products(app, purpose="EQUIPMENT", amount=3_000_000, term=36).values())


# --- 6. Коды ошибок для произвольных HTTP-статусов ---------------------------------------


@pytest.fixture
def raising_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/http/{status}")
    async def http(status: int) -> None:
        raise HTTPException(status_code=status, detail="x")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    return app


@pytest.mark.parametrize(
    ("raised", "status", "code"),
    [
        (400, 400, "BAD_REQUEST"),
        (405, 405, "METHOD_NOT_ALLOWED"),
        (418, 400, "BAD_REQUEST"),  # неизвестный 4xx → статус своего кода
        (429, 429, "TOO_MANY_ATTEMPTS"),
        (500, 500, "INTERNAL_ERROR"),
        (502, 500, "INTERNAL_ERROR"),  # неизвестный 5xx → статус своего кода
        (503, 503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_http_status_gets_matching_code(
    raising_app: FastAPI, raised: int, status: int, code: str
) -> None:
    response = TestClient(raising_app).get(f"/http/{raised}")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


@pytest.mark.parametrize("raised", range(400, 600))
def test_envelope_code_always_matches_http_status(raising_app: FastAPI, raised: int) -> None:
    """Инвариант для любого статуса: ERROR_STATUS[code] == фактический HTTP-статус."""
    response = TestClient(raising_app).get(f"/http/{raised}")
    code = ErrorCode(response.json()["error"]["code"])
    assert ERROR_STATUS[code] == response.status_code


def test_http_exception_headers_are_kept(raising_app: FastAPI) -> None:
    response = TestClient(raising_app).post("/http/405")  # маршрут только GET
    assert response.status_code == 405
    assert response.headers["allow"] == "GET"


def test_unhandled_exception_is_enveloped_without_details(raising_app: FastAPI) -> None:
    response = TestClient(raising_app, raise_server_exceptions=False).get("/boom")
    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервера"}
    }


def test_wrong_method_on_real_route_is_405(app: FastAPI) -> None:
    response = TestClient(app).delete("/api/v1/health")
    assert response.status_code == 405
    assert response.json()["error"]["code"] == "METHOD_NOT_ALLOWED"
