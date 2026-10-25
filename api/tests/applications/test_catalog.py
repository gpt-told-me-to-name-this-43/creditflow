"""GET /credit-products (#7): подбор по design §3.3 из каталога в БД."""

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from tests.applications.conftest import MANAGER, AsUser


@pytest.fixture
async def client_headers(as_user: AsUser) -> dict[str, str]:
    # каталог доступен клиенту и без привязанной компании
    return await as_user("director.newstart@creditflow.demo")


async def products(
    api: httpx.AsyncClient, headers: dict[str, str], **params: str | int
) -> dict[str, dict[str, Any]]:
    response = await api.get("/credit-products", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return {p["id"]: p for p in response.json()}


async def test_catalog_has_both_products_without_filters(
    api: httpx.AsyncClient, client_headers: dict[str, str]
) -> None:
    result = await products(api, client_headers)
    assert set(result) == {"investment", "working_capital"}
    for p in result.values():
        assert p["suitable"] is True and p["unmet_constraints"] == []
        assert p["monthly_payment_rub"] is None  # без суммы и срока платёж не считается
        assert p["disclaimer"]


async def test_c2_request_matches_only_investment(
    api: httpx.AsyncClient, client_headers: dict[str, str]
) -> None:
    result = await products(api, client_headers, purpose="EQUIPMENT", amount=3_000_000, term=36)
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
async def test_working_capital_bounds(
    api: httpx.AsyncClient,
    client_headers: dict[str, str],
    params: dict[str, int],
    expected: list[str],
) -> None:
    result = await products(api, client_headers, **params)
    assert result["working_capital"]["unmet_constraints"] == expected


async def test_openapi_example_matches_c2_query(
    app: FastAPI, api: httpx.AsyncClient, client_headers: dict[str, str]
) -> None:
    op = app.openapi()["paths"]["/api/v1/credit-products"]["get"]
    example = op["responses"]["200"]["content"]["application/json"]["example"]
    real = await products(api, client_headers, purpose="EQUIPMENT", amount=3_000_000, term=36)
    assert example == list(real.values())


async def test_manager_gets_403(api: httpx.AsyncClient, as_user: AsUser) -> None:
    response = await api.get("/credit-products", headers=await as_user(MANAGER))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
