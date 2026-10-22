import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx

from app.extsim_client import (
    CompanyNotInRegistryError,
    ExtSimClient,
    ProviderUnavailableError,
    StatementPeriod,
)
from app.extsim_client.dto import EgripEntrepreneur, EgrulCompany

from .conftest import EXT_SIM_URL, ext_sim_examples

INN = "0099000014"
IE_INN = "009900000200"
CONSENT = "3f2c9a1e-0d7b-4c55-8a9e-1b2c3d4e5f60"
PERIOD = StatementPeriod(from_=date(2025, 10, 1), to=date(2026, 9, 30))
EXAMPLES = ext_sim_examples()


@pytest.fixture
def sim() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=EXT_SIM_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def client() -> AsyncIterator[ExtSimClient]:
    async with ExtSimClient(EXT_SIM_URL) as c:
        yield c


def ok(name: str) -> httpx.Response:
    return httpx.Response(200, json=EXAMPLES[name])


def mock_all(sim: respx.MockRouter) -> dict[str, respx.Route]:
    return {
        "egrul": sim.get(f"/egrul/v1/companies/{INN}").mock(return_value=ok("EgrulCompany")),
        "fns": sim.get(f"/fns/v1/companies/{INN}").mock(return_value=ok("FnsCompanyStatus")),
        "bki": sim.post("/bki/v1/reports").mock(return_value=ok("BkiReport")),
        "bank": sim.get("/bank/v1/statements").mock(return_value=ok("BankStatement")),
    }


async def test_success_parses_typed_dto(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/egrul/v1/companies/{INN}").mock(return_value=ok("EgrulCompany"))
    company = await client.get_egrul_company(INN, request_id="req-1")
    assert isinstance(company, EgrulCompany)
    assert company.registered_at == date(2021, 3, 15)
    assert route.calls.last.request.headers["X-Request-ID"] == "req-1"


async def test_money_is_decimal(sim: respx.MockRouter, client: ExtSimClient) -> None:
    sim.post("/bki/v1/reports").mock(return_value=ok("BkiReport"))
    report = await client.create_bki_report(INN, CONSENT)
    assert report.monthly_payments_total_rub == Decimal("45000.00")
    assert isinstance(report.obligations[0].outstanding_rub, Decimal)


async def test_money_as_json_number_breaks_contract(
    sim: respx.MockRouter, client: ExtSimClient
) -> None:
    body: dict[str, Any] = dict(EXAMPLES["BkiReport"], monthly_payments_total_rub=45000.0)
    route = sim.post("/bki/v1/reports").respond(200, json=body)
    with pytest.raises(ProviderUnavailableError, match="контракт"):
        await client.create_bki_report(INN, CONSENT)
    assert route.call_count == 1


async def test_statement_sends_period(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get("/bank/v1/statements").mock(return_value=ok("BankStatement"))
    statement = await client.get_statement(INN, PERIOD)
    assert statement.transactions[0].amount_rub == Decimal("350000.00")
    params = route.calls.last.request.url.params
    assert dict(params) == {"inn": INN, "from": "2025-10-01", "to": "2026-09-30"}


async def test_timeout_then_retry_succeeds(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/fns/v1/companies/{INN}").mock(
        side_effect=[httpx.ReadTimeout("slow"), ok("FnsCompanyStatus")]
    )
    started = time.perf_counter()
    status = await client.get_fns_status(INN)
    assert status.active_account_blocks == 0
    assert route.call_count == 2
    assert time.perf_counter() - started >= 0.2


async def test_two_timeouts_raise_unavailable(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/fns/v1/companies/{INN}").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await client.get_fns_status(INN)
    assert route.call_count == 2
    assert exc_info.value.source == "fns"


async def test_slow_response_hits_per_attempt_deadline(sim: respx.MockRouter) -> None:
    attempts: list[httpx.Request] = []

    async def slow(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        await asyncio.sleep(1)
        return ok("FnsCompanyStatus")

    sim.get(f"/fns/v1/companies/{INN}").mock(side_effect=slow)
    async with ExtSimClient(EXT_SIM_URL, timeout=0.05, retry_delay=0.01) as fast:
        started = time.perf_counter()
        with pytest.raises(ProviderUnavailableError):
            await fast.get_fns_status(INN)
    assert len(attempts) == 2
    assert time.perf_counter() - started < 0.5


async def test_connect_error_is_retried(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/fns/v1/companies/{INN}").mock(
        side_effect=[httpx.ConnectError("refused"), ok("FnsCompanyStatus")]
    )
    await client.get_fns_status(INN)
    assert route.call_count == 2


async def test_500_is_retried(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/fns/v1/companies/{INN}").mock(
        side_effect=[httpx.Response(500), ok("FnsCompanyStatus")]
    )
    await client.get_fns_status(INN)
    assert route.call_count == 2


async def test_persistent_5xx_raises_with_status(
    sim: respx.MockRouter, client: ExtSimClient
) -> None:
    route = sim.get(f"/fns/v1/companies/{INN}").respond(503)
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await client.get_fns_status(INN)
    assert route.call_count == 2
    assert exc_info.value.status_code == 503


async def test_registry_404_is_not_retried(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/egrul/v1/companies/{INN}").respond(404)
    with pytest.raises(CompanyNotInRegistryError):
        await client.get_egrul_company(INN)
    assert route.call_count == 1


async def test_bki_403_is_not_retried(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.post("/bki/v1/reports").respond(403)
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await client.create_bki_report(INN, CONSENT)
    assert route.call_count == 1
    assert exc_info.value.status_code == 403


async def test_non_registry_404_is_not_retried(sim: respx.MockRouter, client: ExtSimClient) -> None:
    route = sim.get(f"/fns/v1/companies/{INN}").respond(404)
    with pytest.raises(ProviderUnavailableError):
        await client.get_fns_status(INN)
    assert route.call_count == 1


async def test_bki_is_not_called_without_consent(
    sim: respx.MockRouter, client: ExtSimClient
) -> None:
    route = sim.post("/bki/v1/reports").mock(return_value=ok("BkiReport"))
    with pytest.raises(ValueError, match="consent_id"):
        await client.create_bki_report(INN, "")
    assert route.call_count == 0


async def test_registry_record_dispatch(sim: respx.MockRouter, client: ExtSimClient) -> None:
    sim.get(f"/egrip/v1/entrepreneurs/{IE_INN}").mock(return_value=ok("EgripEntrepreneur"))
    assert isinstance(await client.get_registry_record(IE_INN), EgripEntrepreneur)
    with pytest.raises(ValueError):
        await client.get_registry_record("123")


async def test_fetch_all_for_submit(sim: respx.MockRouter, client: ExtSimClient) -> None:
    routes = mock_all(sim)
    data = await client.fetch_all_for_submit(INN, CONSENT, PERIOD, request_id="req-submit")
    assert isinstance(data.registry, EgrulCompany)
    assert data.bki.summary_status == "CLEAN"
    for route in routes.values():
        assert route.call_count == 1
        assert route.calls.last.request.headers["X-Request-ID"] == "req-submit"
    assert routes["bki"].calls.last.request.content == (
        b'{"inn":"0099000014","consent_id":"3f2c9a1e-0d7b-4c55-8a9e-1b2c3d4e5f60"}'
    )


async def test_fetch_all_for_submit_runs_in_parallel(sim: respx.MockRouter) -> None:
    async def delayed(response: httpx.Response) -> httpx.Response:
        await asyncio.sleep(0.2)
        return response

    for route in mock_all(sim).values():
        response = route.return_value
        assert response is not None
        route.mock(side_effect=lambda request, r=response: delayed(r))
    async with ExtSimClient(EXT_SIM_URL) as c:
        started = time.perf_counter()
        await c.fetch_all_for_submit(INN, CONSENT, PERIOD)
    assert time.perf_counter() - started < 0.6


@pytest.mark.parametrize("failing", ["egrul", "fns", "bki", "bank"])
async def test_fetch_all_for_submit_fails_as_a_whole(
    sim: respx.MockRouter, client: ExtSimClient, failing: str
) -> None:
    routes = mock_all(sim)
    routes[failing].respond(503)
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await client.fetch_all_for_submit(INN, CONSENT, PERIOD)
    assert exc_info.value.source == failing
    assert routes[failing].call_count == 2


async def test_fetch_all_for_submit_company_not_in_registry(
    sim: respx.MockRouter, client: ExtSimClient
) -> None:
    routes = mock_all(sim)
    routes["egrul"].respond(404)
    with pytest.raises(CompanyNotInRegistryError):
        await client.fetch_all_for_submit(INN, CONSENT, PERIOD)


async def test_health(sim: respx.MockRouter, client: ExtSimClient) -> None:
    sim.get("/health").mock(side_effect=[httpx.Response(200), httpx.ConnectError("down")])
    assert await client.health() is True
    assert await client.health() is False
