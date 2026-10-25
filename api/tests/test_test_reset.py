"""`POST /_test/reset` (design §4): только при флаге, только с верным токеном, иначе 404."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

TOKEN = "t" * 32
URL = "/api/v1/_test/reset"


def post(
    settings: Settings, mode: str = "clean", token: str | None = TOKEN
) -> tuple[int, dict[str, Any]]:
    headers = {} if token is None else {"X-Test-Reset-Token": token}
    response = TestClient(create_app(settings)).post(URL, params={"mode": mode}, headers=headers)
    return response.status_code, response.json()


def test_not_mounted_when_disabled(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(test_reset_enabled=False, test_reset_token=TOKEN)
    assert post(settings)[0] == 404
    assert "/api/v1/_test/reset" not in create_app(settings).openapi()["paths"]


@pytest.mark.parametrize("mode", ["clean", "demo"])
def test_valid_token_resets(make_settings: Callable[..., Settings], mode: str) -> None:
    settings = make_settings(test_reset_enabled=True, test_reset_token=TOKEN)
    assert post(settings, mode) == (200, {"mode": mode})


@pytest.mark.parametrize(
    ("configured", "given"),
    [
        (TOKEN, None),  # нет заголовка
        (TOKEN, "x" * 32),  # чужой токен
        (None, TOKEN),  # токен не настроен
        ("short", "short"),  # токен в конфиге короче 32 байт — fail-closed
    ],
)
def test_bad_token_is_plain_404(
    make_settings: Callable[..., Settings], configured: str | None, given: str | None
) -> None:
    settings = make_settings(test_reset_enabled=True, test_reset_token=configured)
    status, body = post(settings, token=given)
    assert status == 404
    assert body["error"]["code"] == "NOT_FOUND"


def test_unknown_mode_is_validation_error(make_settings: Callable[..., Settings]) -> None:
    settings = make_settings(test_reset_enabled=True, test_reset_token=TOKEN)
    assert post(settings, mode="drop")[0] == 422


@pytest.mark.parametrize("mode", ["drop", ""])
def test_token_checked_before_mode_validation(
    make_settings: Callable[..., Settings], mode: str
) -> None:
    settings = make_settings(test_reset_enabled=True, test_reset_token=TOKEN)
    assert post(settings, mode=mode, token=None)[0] == 404


def test_reset_contract_only_exposed_when_enabled(make_settings: Callable[..., Settings]) -> None:
    for env in ["local", "test"]:
        spec = create_app(
            make_settings(app_env=env, test_reset_enabled=True, test_reset_token=TOKEN)
        ).openapi()
        operation = spec["paths"][URL]["post"]
        assert operation["security"] == [{"TestResetToken": []}]
        assert (
            spec["components"]["securitySchemes"]["TestResetToken"]["name"] == "X-Test-Reset-Token"
        )
    production = create_app(make_settings(app_env="production", test_reset_enabled=False)).openapi()
    assert URL not in production["paths"]


@pytest.mark.parametrize("token", [None, "x" * 32])
@pytest.mark.parametrize("query", [{"mode": "drop"}, {"mode": "clean"}, {}])
def test_rejection_is_byte_identical_to_unknown_route(
    make_settings: Callable[..., Settings], token: str | None, query: dict[str, str]
) -> None:
    """design §4: неверный токен (в том числе с неверным mode) — тот же 404, что у
    незарегистрированного маршрута: статус, тело и заголовки."""
    client = TestClient(create_app(make_settings(test_reset_enabled=True, test_reset_token=TOKEN)))
    headers = {"X-Request-ID": "same-request-id"}
    if token is not None:
        headers["X-Test-Reset-Token"] = token
    rejected = client.post(URL, params=query, headers=headers)
    unknown = client.post("/api/v1/_test/no-such-route", params=query, headers=headers)
    assert rejected.status_code == unknown.status_code == 404
    assert rejected.content == unknown.content
    assert rejected.headers.items() == unknown.headers.items()
