"""Временная аутентификация реализованных маршрутов (#7 до #5): JWT HS256, роль, привязка."""

import uuid
from collections.abc import Callable

import httpx
import pytest

from app.core.config import Settings
from app.core.security import decode_token, encode_token
from app.schemas.auth import Role
from tests.applications.conftest import BAKERY, MANAGER, AsUser
from tests.conftest import TEST_SECRET_KEY


def test_token_roundtrip() -> None:
    user_id = uuid.uuid4()
    claims = decode_token(encode_token(user_id, Role.CLIENT, TEST_SECRET_KEY), TEST_SECRET_KEY)
    assert claims is not None
    assert claims["sub"] == str(user_id) and claims["role"] == "CLIENT"


@pytest.mark.parametrize(
    "token",
    [
        "garbage",
        "a.b.c",
        encode_token(uuid.uuid4(), Role.CLIENT, "other-secret"),
        encode_token(uuid.uuid4(), Role.CLIENT, TEST_SECRET_KEY, ttl=-1),
    ],
    ids=["garbage", "malformed", "wrong-signature", "expired"],
)
def test_invalid_tokens_are_rejected(token: str) -> None:
    assert decode_token(token, TEST_SECRET_KEY) is None


def test_empty_secret_never_validates_or_issues() -> None:
    assert decode_token(encode_token(uuid.uuid4(), Role.CLIENT, "x"), "") is None
    with pytest.raises(ValueError, match="APP_SECRET_KEY"):
        encode_token(uuid.uuid4(), Role.CLIENT, "")


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer contract-stub-token"},
        {"Authorization": "Bearer " + encode_token(uuid.uuid4(), Role.CLIENT, TEST_SECRET_KEY)},
    ],
    ids=["no-bearer", "stub-token", "unknown-user"],
)
async def test_implemented_routes_require_valid_token(
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


def test_settings_secret_used_by_tests(make_settings: Callable[..., Settings]) -> None:
    assert make_settings().app_secret_key == TEST_SECRET_KEY
