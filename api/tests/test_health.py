from collections.abc import Callable, Iterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

from .conftest import DEAD_DATABASE_URL, EXT_SIM_URL


@pytest.fixture
def ext_sim() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=EXT_SIM_URL, assert_all_called=False) as router:
        yield router


def get_health(settings: Settings) -> httpx.Response:
    with TestClient(create_app(settings)) as client:
        return client.get("/api/v1/health")


def test_health_ok(make_settings: Callable[..., Settings], ext_sim: respx.MockRouter) -> None:
    ext_sim.get("/health").respond(200, json={"status": "ok"})
    response = get_health(make_settings())
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "ext_sim": "ok", "llm": "replay"}


def test_health_db_unavailable(
    make_settings: Callable[..., Settings], ext_sim: respx.MockRouter
) -> None:
    ext_sim.get("/health").respond(200, json={"status": "ok"})
    response = get_health(make_settings(database_url=DEAD_DATABASE_URL))
    assert response.status_code == 503
    body = response.json()
    assert (body["status"], body["db"], body["ext_sim"]) == ("unavailable", "unavailable", "ok")


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.Response(503)],
    ids=["connect", "timeout", "http-503"],
)
def test_health_ext_sim_unavailable(
    make_settings: Callable[..., Settings],
    ext_sim: respx.MockRouter,
    failure: Exception | httpx.Response,
) -> None:
    ext_sim.get("/health").mock(side_effect=[failure])
    response = get_health(make_settings())
    assert response.status_code == 503
    body = response.json()
    assert (body["status"], body["db"], body["ext_sim"]) == ("unavailable", "ok", "unavailable")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"llm_mode": "replay"}, "replay"),
        ({"llm_mode": "disabled"}, "disabled"),
        ({"llm_mode": "openai", "llm_base_url": None}, "not_configured"),
        ({"llm_mode": "openai", "llm_base_url": "https://openrouter.ai/api/v1"}, "ok"),
    ],
)
def test_health_llm_from_config_does_not_affect_status(
    make_settings: Callable[..., Settings],
    ext_sim: respx.MockRouter,
    overrides: dict[str, str | None],
    expected: str,
) -> None:
    ext_sim.get("/health").respond(200, json={"status": "ok"})
    response = get_health(make_settings(**overrides))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["llm"] == expected


def test_swagger_is_served_under_api(make_settings: Callable[..., Settings]) -> None:
    with TestClient(create_app(make_settings())) as client:
        assert client.get("/api/docs").status_code == 200
        assert client.get("/api/openapi.json").status_code == 200
