import json
from pathlib import Path

import httpx
import pytest

from app.fixtures import DEFAULT_FIXTURES_DIR
from app.main import create_app
from app.schemas import BankStatement, BkiReport, EgripEntrepreneur, EgrulCompany, FnsCompanyStatus

from .conftest import IE_INN, IE_RECORD, SAMPLE_INN

CONSENT = "3f2c9a1e-0d7b-4c55-8a9e-1b2c3d4e5f60"
UNKNOWN_LLC = "0099999990"


def example(model: type[object]) -> object:
    schema = model.model_json_schema(by_alias=True)  # type: ignore[attr-defined]
    return schema["examples"][0]


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_egrul_company(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/egrul/v1/companies/{SAMPLE_INN}")
    assert response.status_code == 200
    assert response.json() == example(EgrulCompany)


async def test_egrip_entrepreneur(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/egrip/v1/entrepreneurs/{IE_INN}")
    assert response.status_code == 200
    assert response.json() == IE_RECORD == example(EgripEntrepreneur)


async def test_fns_company(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/fns/v1/companies/{SAMPLE_INN}")
    assert response.status_code == 200
    assert response.json() == example(FnsCompanyStatus)


async def test_bki_report(client: httpx.AsyncClient) -> None:
    response = await client.post("/bki/v1/reports", json={"inn": SAMPLE_INN, "consent_id": CONSENT})
    assert response.status_code == 200
    body = response.json()
    expected = example(BkiReport)
    assert isinstance(expected, dict)
    assert {k: v for k, v in body.items() if k != "report_id"} == {
        k: v for k, v in expected.items() if k != "report_id"
    }
    again = await client.post("/bki/v1/reports", json={"inn": SAMPLE_INN, "consent_id": CONSENT})
    assert again.json()["report_id"] == body["report_id"]


async def test_bank_statement_filters_period(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/bank/v1/statements", params={"inn": SAMPLE_INN, "from": "2026-09-01", "to": "2026-09-30"}
    )
    assert response.status_code == 200
    body = response.json()
    assert [t["booked_at"] for t in body["transactions"]] == [
        "2026-09-05",
        "2026-09-10",
        "2026-09-25",
    ]
    assert body["transactions"][0] == example(BankStatement)["transactions"][0]  # type: ignore[index]
    assert {k: body[k] for k in ("inn", "from", "to")} == {
        "inn": SAMPLE_INN,
        "from": "2026-09-01",
        "to": "2026-09-30",
    }


async def test_money_is_string(client: httpx.AsyncClient) -> None:
    response = await client.get(
        "/bank/v1/statements", params={"inn": SAMPLE_INN, "from": "2026-01-01", "to": "2026-12-31"}
    )
    amounts = [t["amount_rub"] for t in response.json()["transactions"]]
    assert amounts and all(isinstance(a, str) for a in amounts)
    assert "120000.50" in amounts


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("GET", f"/egrul/v1/companies/{UNKNOWN_LLC}", None),
        ("GET", f"/egrul/v1/companies/{'0' * 10}", None),
        ("GET", f"/egrip/v1/entrepreneurs/{'0' * 12}", None),
        ("GET", f"/fns/v1/companies/{UNKNOWN_LLC}", None),
        ("GET", f"/fns/v1/companies/{IE_INN}", None),
        ("POST", "/bki/v1/reports", {"inn": UNKNOWN_LLC, "consent_id": CONSENT}),
        ("GET", f"/bank/v1/statements?inn={UNKNOWN_LLC}&from=2026-01-01&to=2026-02-01", None),
    ],
)
async def test_not_found(
    client: httpx.AsyncClient, method: str, url: str, body: dict[str, str] | None
) -> None:
    response = await client.request(method, url, json=body)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_egrip_for_llc_inn_is_not_found(client: httpx.AsyncClient) -> None:
    # ИНН ЮЛ не проходит по формату ЕГРИП (12 цифр).
    response = await client.get(f"/egrip/v1/entrepreneurs/{SAMPLE_INN}")
    assert response.status_code == 422


@pytest.mark.parametrize("body", [{"inn": SAMPLE_INN}, {"inn": SAMPLE_INN, "consent_id": ""}])
async def test_bki_without_consent_is_forbidden(
    client: httpx.AsyncClient, body: dict[str, str]
) -> None:
    response = await client.post("/bki/v1/reports", json=body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


@pytest.mark.parametrize(
    "params",
    [
        {"inn": SAMPLE_INN, "from": "2026-10-01", "to": "2026-09-01"},
        {"inn": SAMPLE_INN, "from": "not-a-date", "to": "2026-09-01"},
        {"inn": SAMPLE_INN, "to": "2026-09-01"},
        {"inn": "123", "from": "2026-09-01", "to": "2026-09-30"},
    ],
)
async def test_bank_statement_validation(client: httpx.AsyncClient, params: dict[str, str]) -> None:
    response = await client.get("/bank/v1/statements", params=params)
    assert response.status_code == 422
    assert "error" in response.json()


async def test_request_id_is_echoed(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"X-Request-ID": "req-123"})
    assert response.headers["X-Request-ID"] == "req-123"


async def test_request_id_generated_when_missing_or_invalid(client: httpx.AsyncClient) -> None:
    missing = await client.get("/health")
    invalid = await client.get("/health", headers={"X-Request-ID": "bad id\twith spaces"})
    assert len(missing.headers["X-Request-ID"]) == 36
    assert invalid.headers["X-Request-ID"] != "bad id\twith spaces"


async def test_response_bodies_are_not_logged(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="ext_sim")
    await client.get(f"/egrul/v1/companies/{SAMPLE_INN}", headers={"X-Request-ID": "req-log"})
    assert "request_id=req-log" in caplog.text
    assert "Образцов" not in caplog.text


def test_shipped_fixtures_load() -> None:
    create_app(DEFAULT_FIXTURES_DIR)


def test_broken_fixture_fails_startup(fixtures_dir: Path) -> None:
    (fixtures_dir / SAMPLE_INN / "fns.json").write_text(
        json.dumps({"bankruptcy": False, "active_account_blocks": -1, "checked_at": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        create_app(fixtures_dir)


def test_fixture_inn_must_match_directory(fixtures_dir: Path) -> None:
    (fixtures_dir / SAMPLE_INN).rename(fixtures_dir / UNKNOWN_LLC)
    with pytest.raises(ValueError, match="ИНН"):
        create_app(fixtures_dir)
