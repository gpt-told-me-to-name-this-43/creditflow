import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app import main
from app.main import create_app

from .conftest import SAMPLE_INN

CONSENT = "3f2c9a1e-0d7b-4c55-8a9e-1b2c3d4e5f60"
FAILING_INN = "0099009999"

REQUESTS: dict[str, tuple[str, str, dict[str, str] | None]] = {
    "egrul": ("GET", "/egrul/v1/companies/{inn}", None),
    "fns": ("GET", "/fns/v1/companies/{inn}", None),
    "bki": ("POST", "/bki/v1/reports", {"inn": "{inn}", "consent_id": CONSENT}),
    "bank": ("GET", "/bank/v1/statements?inn={inn}&from=2026-01-01&to=2026-12-31", None),
}


async def call(client: httpx.AsyncClient, source: str, inn: str, **kwargs: Any) -> httpx.Response:
    method, url, body = REQUESTS[source]
    json_body = {k: v.format(inn=inn) for k, v in body.items()} if body else None
    return await client.request(method, url.format(inn=inn), json=json_body, **kwargs)


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "TIMEOUT_SLEEP_SECONDS", 0.05)


# В начале файла test_failures.py

EXPECTED = {
    "bki_timeout": (504, "SIMULATED_TIMEOUT"),
    "fns_timeout": (504, "SIMULATED_TIMEOUT"),
    "egrul_timeout": (504, "SIMULATED_TIMEOUT"),
    "egrip_timeout": (504, "SIMULATED_TIMEOUT"),
}


@pytest.mark.parametrize("source", sorted(REQUESTS))
@pytest.mark.parametrize("mode", sorted(EXPECTED))
async def test_x_sim_fail_header(client: httpx.AsyncClient, source: str, mode: str) -> None:
    response = await call(client, source, SAMPLE_INN, headers={"X-Sim-Fail": mode})
    status, code = EXPECTED[mode]
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_x_sim_fail_timeout_holds_connection(client: httpx.AsyncClient) -> None:
    started = time.perf_counter()
    await call(client, "egrul", SAMPLE_INN, headers={"X-Sim-Fail": "egrul_timeout"})
    assert time.perf_counter() - started >= 0.05


async def test_x_sim_fail_unknown_value(client: httpx.AsyncClient) -> None:
    response = await call(client, "egrul", SAMPLE_INN, headers={"X-Sim-Fail": "teapot"})
    assert response.status_code == 422


async def test_x_sim_latency(client: httpx.AsyncClient) -> None:
    started = time.perf_counter()
    response = await call(client, "fns", SAMPLE_INN, headers={"X-Sim-Latency-Ms": "100"})
    assert response.status_code == 200
    assert time.perf_counter() - started >= 0.1


@pytest.mark.parametrize("value", ["-1", "30001", "abc"])
async def test_x_sim_latency_out_of_range(client: httpx.AsyncClient, value: str) -> None:
    response = await call(client, "fns", SAMPLE_INN, headers={"X-Sim-Latency-Ms": value})
    assert response.status_code == 422


@pytest.mark.parametrize("mode", sorted(EXPECTED))
@pytest.mark.parametrize("source", sorted(REQUESTS))
async def test_fixture_fail_mode_affects_only_its_source(
    add_company: Callable[[str, dict[str, Any]], Path],
    fixtures_dir: Path,
    make_client: Callable[[FastAPI], httpx.AsyncClient],
    source: str,
    mode: str,
) -> None:
    add_company(FAILING_INN, {"meta.json": {"fail_mode": f"{source}_{mode}"}})
    async with make_client(create_app(fixtures_dir)) as client:
        for other in REQUESTS:
            response = await call(client, other, FAILING_INN)
            if other == source:
                assert response.status_code == EXPECTED[mode][0]
            else:
                assert response.status_code == 200, other


@pytest.mark.parametrize("fail_mode", ["bki", "bki_418", "ldap_timeout"])
def test_invalid_fixture_fail_mode(
    add_company: Callable[[str, dict[str, Any]], Path], fixtures_dir: Path, fail_mode: str
) -> None:
    add_company(FAILING_INN, {"meta.json": {"fail_mode": fail_mode}})
    with pytest.raises(ValueError):
        create_app(fixtures_dir)
