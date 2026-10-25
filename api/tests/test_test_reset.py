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


# Сброс с верным токеном на живой БД — tests/applications/test_demo.py (#7).


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
