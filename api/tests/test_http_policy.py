"""Явная матрица contract-v1: применимость ошибок, а не шесть статусов на всё."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import TypeAdapter

from app.core.config import Settings
from app.core.errors import AppError, install_error_handlers
from app.main import create_app
from app.schemas.common import ERROR_STATUS, ErrorCode, ErrorEnvelope
from contract.matrix import Operation, load_matrix, wire_schema

OPERATIONS = load_matrix().operations
# Настоящие маршруты #5: монтируются и в production.
ACCESS_PATHS = ("/api/v1/auth/", "/api/v1/consents/", "/api/v1/onboarding/", "/api/v1/company")


@pytest.fixture
def app(make_settings: Callable[..., Settings]) -> FastAPI:
    return create_app(make_settings(test_reset_enabled=True, test_reset_token="r" * 32))


def registered_routes(routes: list[Any], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """FastAPI 0.159 хранит include_router как вложенный маршрут."""
    for route in routes:
        if isinstance(route, APIRoute) and route.include_in_schema:
            yield prefix + route.path, route
        elif hasattr(route, "original_router"):
            yield from registered_routes(
                route.original_router.routes, prefix + route.include_context.prefix
            )


def test_matrix_covers_registered_operations_and_response_models(app: FastAPI) -> None:
    expected = {(op.method, op.path) for op in OPERATIONS}
    spec = app.openapi()
    actual = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    routes = list(registered_routes(app.routes))
    assert (
        actual
        == expected
        == {(method, path) for path, route in routes for method in route.methods or ()}
    )
    for path, route in routes:
        if route.status_code == 204:
            assert route.response_model is None
            continue
        assert route.response_model is not None, path
        # Сравниваем сам response_model зарегистрированного маршрута с wire-схемой.
        model_schema = TypeAdapter(route.response_model).json_schema(
            mode="serialization", ref_template="#/components/schemas/{model}"
        )
        model_schema.pop("$defs", None)
        # FastAPI исключает default:null; это не меняет nullable или required.
        for prop in model_schema.get("properties", {}).values():
            if prop.get("default", "absent") is None:
                prop.pop("default")
        for method in route.methods or ():
            response = spec["paths"][path][method.lower()]["responses"][
                str(route.status_code or 200)
            ]
            schema = response["content"]["application/json"]["schema"]
            if "$ref" in schema:
                assert spec["components"]["schemas"][schema["$ref"].split("/")[-1]] == model_schema
            else:
                assert schema.get("type") == model_schema.get("type")
                assert schema.get("discriminator") == model_schema.get("discriminator")


@pytest.mark.parametrize("op", OPERATIONS, ids=lambda op: f"{op.method} {op.path}")
def test_operation_statuses_codes_and_security(app: FastAPI, op: Operation) -> None:
    operation = app.openapi()["paths"][op.path][op.method.lower()]
    assert {int(s) for s in operation["responses"]} == set(op.responses)
    security: list[dict[str, list[str]]]
    if op.access == "public":
        security = []
    elif op.access == "TestResetToken":
        security = [{"TestResetToken": []}]
    else:
        security = [{"BearerAuth": []}]
    assert operation.get("security", []) == security
    for status, expected_response in op.responses.items():
        if status < 400:
            if status == 204:
                assert "content" not in operation["responses"][str(status)]
            else:
                schema = operation["responses"][str(status)]["content"]["application/json"][
                    "schema"
                ]
                expected_schema = wire_schema(expected_response.model)
                assert all(schema.get(k) == v for k, v in expected_schema.items())
            continue
        response = operation["responses"][str(status)]
        content = response["content"]["application/json"]
        if op.path == "/api/v1/health":
            assert content["schema"] == {"$ref": "#/components/schemas/HealthResponse"}
            continue
        assert content["schema"] == {"$ref": "#/components/schemas/ErrorEnvelope"}
        expected = set(expected_response.codes)
        assert set(content["examples"]) == expected
        if expected_response.retry_after is not None:
            assert ("Retry-After" in response.get("headers", {})) == expected_response.retry_after
        for code in expected:
            envelope = ErrorEnvelope.model_validate(content["examples"][code]["value"])
            assert ERROR_STATUS[envelope.error.code] == status


@pytest.mark.parametrize("code", list(ErrorCode))
def test_domain_error_runtime_status_envelope_and_headers(code: ErrorCode) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/error")
    async def error() -> None:
        raise AppError(code, "Ошибка", headers={"Retry-After": "60", "Allow": "POST"})

    response = TestClient(app).get("/error")
    envelope = ErrorEnvelope.model_validate(response.json())
    assert envelope.error.code == code
    assert response.status_code == ERROR_STATUS[code]
    assert response.headers["Retry-After"] == "60"
    assert response.headers["Allow"] == "POST"


def test_http_exception_retry_after_is_preserved() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/limit")
    async def limit() -> None:
        raise HTTPException(429, "Повторите позже", headers={"Retry-After": "120"})

    response = TestClient(app).get("/limit")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "120"
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"


@pytest.mark.parametrize("env", ["local", "test", "production"])
def test_environment_route_boundary(make_settings: Callable[..., Settings], env: str) -> None:
    app = create_app(make_settings(app_env=env))
    paths = app.openapi()["paths"]
    assert "/api/v1/_test/reset" not in paths
    assert len(paths) == (7 if env == "production" else 25)
    if env == "production":
        client = TestClient(app, headers={"Authorization": "Bearer anything"})
        for op in OPERATIONS:
            if op.path != "/api/v1/health" and not op.path.startswith(ACCESS_PATHS):
                response = client.request(op.method, op.path)
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "NOT_FOUND"
