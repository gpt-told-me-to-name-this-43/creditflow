"""Матрица «роль × эндпоинт» во время выполнения (#5, design.md §4 «RBAC»).

Маршруты берутся из `app.routes`, ожидаемый доступ — из `access` в
`api/contract/http_matrix.yaml`. Для каждого маршрута проверяются аноним, CLIENT и MANAGER.
Отказ доступа — только `401 UNAUTHORIZED` и `403 FORBIDDEN`; бизнес-ответы (409, 422,
`403 APPLICANT_NOT_AUTHORIZED`) означают, что проверку доступа запрос прошёл.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import stubs
from app.auth.deps import current_user, require_role
from app.core.config import Settings
from app.main import create_app
from app.schemas.auth import Role
from app.schemas.manager import ManagerStats
from contract.matrix import load_matrix
from tests.conftest import CLIENT_LOGIN, MANAGER_LOGIN, bearer
from tests.test_http_policy import registered_routes

ACCESS: dict[tuple[str, str], str] = {
    (op.method, op.path): op.access for op in load_matrix().operations
}
DENIED = {"UNAUTHORIZED", "FORBIDDEN"}
# Маршруты, которые матрица описывает, но которых нет в обычном приложении: /_test/reset
# монтируется только при TEST_RESET_ENABLED (его доступ проверяет test_test_reset.py).
CONDITIONAL = {("POST", "/api/v1/_test/reset")}
# Кто проходит проверку доступа при данном `access`.
ALLOWED: dict[str, set[str]] = {
    "public": {"anonymous", "CLIENT", "MANAGER"},
    "Bearer": {"CLIENT", "MANAGER"},
    "CLIENT": {"CLIENT"},
    "MANAGER": {"MANAGER"},
}
CALLERS = {
    "anonymous": {},
    "CLIENT": bearer(CLIENT_LOGIN),
    "MANAGER": bearer(MANAGER_LOGIN),
}


def access_violations(app: FastAPI) -> list[str]:
    client = TestClient(app)
    problems: list[str] = []
    for path, route in registered_routes(app.routes):
        for method in sorted(route.methods or ()):
            key = (method, path)
            access = ACCESS.get(key)
            if access is None:
                problems.append(f"{method} {path}: нет в http_matrix.yaml")
                continue
            url = path.replace("{application_id}", str(uuid.uuid4()))
            body: dict[str, Any] | None = {} if method in {"POST", "PATCH"} else None
            for caller, headers in CALLERS.items():
                response = client.request(method, url, json=body, headers=headers)
                payload = response.json()
                code = (
                    payload["error"]["code"]
                    if isinstance(payload, dict) and "error" in payload
                    else None
                )
                if caller in ALLOWED[access]:
                    if code in DENIED:
                        problems.append(f"{method} {path} {caller}: отказ {code}, ждали доступ")
                elif caller == "anonymous":
                    if (response.status_code, code) != (401, "UNAUTHORIZED"):
                        problems.append(
                            f"{method} {path} anonymous: {response.status_code} {code}, ждали 401"
                        )
                elif (response.status_code, code) != (403, "FORBIDDEN"):
                    problems.append(
                        f"{method} {path} {caller}: {response.status_code} {code}, ждали 403"
                    )
    return problems


@pytest.fixture
def start(
    make_settings: Callable[..., Settings], db_reset: None, running: Callable[[Any], Any]
) -> Callable[..., FastAPI]:
    def make(**overrides: Any) -> FastAPI:
        app: FastAPI = running(create_app(make_settings(**overrides)))
        return app

    return make


@pytest.mark.parametrize("env", ["test", "production"])
def test_every_route_matches_matrix(start: Callable[..., FastAPI], env: str) -> None:
    app = start(app_env=env)
    routes = {(m, p) for p, r in registered_routes(app.routes) for m in r.methods or ()}
    expected = set(ACCESS) - CONDITIONAL
    if env == "production":
        expected = {
            k
            for k in expected
            if not k[1].startswith(
                ("/api/v1/applications", "/api/v1/manager", "/api/v1/credit-products")
            )
        }
    assert routes == expected
    assert access_violations(app) == []


def _app_with(start: Callable[..., FastAPI], router: APIRouter) -> FastAPI:
    # production: стабы не смонтированы, поэтому добавленный маршрут — единственный по пути.
    app = start(app_env="production")
    app.include_router(router, prefix="/api/v1")
    return app


def test_route_missing_from_matrix_fails(start: Callable[..., FastAPI]) -> None:
    router = APIRouter(prefix="/manager", dependencies=[Depends(require_role(Role.MANAGER))])
    router.add_api_route("/secret", stubs.stats, methods=["GET"], response_model=ManagerStats)
    assert access_violations(_app_with(start, router)) == [
        "GET /api/v1/manager/secret: нет в http_matrix.yaml"
    ]


def test_route_without_require_role_fails(start: Callable[..., FastAPI]) -> None:
    """Негативная проверка: у менеджерского маршрута снят require_role — клиент проходит."""
    router = APIRouter(prefix="/manager", dependencies=[Depends(current_user)])
    router.add_api_route("/stats", stubs.stats, methods=["GET"], response_model=ManagerStats)
    assert access_violations(_app_with(start, router)) == [
        "GET /api/v1/manager/stats CLIENT: 200 None, ждали 403"
    ]


def test_route_without_any_auth_fails(start: Callable[..., FastAPI]) -> None:
    router = APIRouter(prefix="/manager")
    router.add_api_route("/stats", stubs.stats, methods=["GET"], response_model=ManagerStats)
    assert access_violations(_app_with(start, router)) == [
        "GET /api/v1/manager/stats anonymous: 200 None, ждали 401",
        "GET /api/v1/manager/stats CLIENT: 200 None, ждали 403",
    ]


def test_client_cannot_reach_manager_routes(start: Callable[..., FastAPI]) -> None:
    client = TestClient(start(), headers=bearer(CLIENT_LOGIN))
    for (method, path), access in ACCESS.items():
        if access == "MANAGER":
            url = path.replace("{application_id}", str(uuid.uuid4()))
            response = client.request(method, url, json={})
            assert response.status_code == 403, (method, path)
            assert response.json()["error"]["code"] == "FORBIDDEN"
