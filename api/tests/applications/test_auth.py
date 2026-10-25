"""Доступ к маршрутам конвейера (#7) поверх #5: роль, привязка компании, неизвестный токен."""

import uuid

import httpx
import pytest

from app.auth.tokens import issue_token
from tests.applications.conftest import BAKERY, MANAGER, AsUser
from tests.conftest import TEST_SECRET_KEY


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Bearer " + issue_token(uuid.uuid4(), "CLIENT", TEST_SECRET_KEY)},
    ],
    ids=["no-bearer", "garbage", "unknown-user"],
)
async def test_pipeline_routes_require_valid_token(
    api: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    response = await api.get("/applications", headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


async def test_manager_cannot_use_client_routes(api: httpx.AsyncClient, as_user: AsUser) -> None:
    response = await api.post("/applications", json={}, headers=await as_user(MANAGER))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/applications"), ("POST", "/applications"), ("GET", f"/applications/{uuid.uuid4()}")],
)
async def test_unbound_client_gets_company_not_bound(
    api: httpx.AsyncClient, as_user: AsUser, method: str, path: str
) -> None:
    body: dict[str, str] | None = {} if method == "POST" else None
    response = await api.request(method, path, json=body, headers=await as_user(BAKERY))
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMPANY_NOT_BOUND"
