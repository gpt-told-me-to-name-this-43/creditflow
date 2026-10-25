"""Привязка компании, согласия, нормализация ФИО и ИНН (#5)."""

import asyncio
import json
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import sqlalchemy as sa

from app.core.config import Settings
from app.extsim_client import ExtSimClient
from app.extsim_client.dto import RegistryRecord
from app.main import create_app
from app.onboarding.authorization import is_authorized_applicant, normalize_full_name
from app.onboarding.inn import is_valid_inn
from app.seed import DEMO_USERS
from tests.conftest import EXT_SIM_URL, MANAGER_LOGIN, REPO_ROOT, TEST_DATABASE_URL, bearer

FIXTURES = REPO_ROOT / "ext-sim" / "fixtures"
BINDING = "/api/v1/onboarding/company-binding"
BAKERY_INN = "0099020010"
BAKERY_DIRECTOR = "director.bakery@creditflow.demo"
ACCOUNTANT = "accountant.bakery@creditflow.demo"
SOKOLOVA = "ip.sokolova@creditflow.demo"
SOKOLOVA_INN = "009903001040"
TECH_INN, TECH_DIRECTOR = "0099010012", "director.techservice@creditflow.demo"

Serve = Callable[[Any], Awaitable[httpx.AsyncClient]]


def registry(inn: str) -> dict[str, Any]:
    name = "egrul.json" if len(inn) == 10 else "egrip.json"
    data: dict[str, Any] = json.loads((FIXTURES / inn / name).read_text("utf-8"))
    return data


@pytest.fixture
def sim() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=EXT_SIM_URL, assert_all_called=False) as router:
        for path in FIXTURES.iterdir():
            if path.is_dir():
                kind = "egrul/v1/companies" if len(path.name) == 10 else "egrip/v1/entrepreneurs"
                router.get(f"/{kind}/{path.name}").respond(200, json=registry(path.name))
        router.get(url__regex=r"/(egrul/v1/companies|egrip/v1/entrepreneurs)/\d+").respond(
            404, json={"detail": "not found"}
        )
        yield router


@pytest.fixture
async def api(
    make_settings: Callable[..., Settings], db_reset: None, sim: respx.MockRouter, serve: Serve
) -> httpx.AsyncClient:
    return await serve(create_app(make_settings()))


def bind(api: httpx.AsyncClient, login: str, inn: str, version: str = "pd-v1") -> Any:
    return api.post(
        BINDING, json={"inn": inn, "pd_consent_version": version}, headers=bearer(login)
    )


def db_counts() -> dict[str, int]:
    engine = sa.create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        counts = {
            table: conn.scalar(sa.text(f"SELECT count(*) FROM {table}"))
            for table in ("companies", "consents", "external_snapshots")
        }
        counts["bound_users"] = conn.scalar(
            sa.text("SELECT count(*) FROM users WHERE company_id IS NOT NULL")
        )
    engine.dispose()
    return counts


# --- Нормализация ФИО и ИНН ------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        "Соколова Алёна Викторовна",
        "соколова  алена викторовна",
        "  СОКОЛОВА\tАЛЁНА\nВикторовна ",
        unicodedata.normalize("NFD", "Соколова Алёна Викторовна"),
        "Соколова АЛЕНА викторовна",
    ],
)
def test_full_name_normalization(variant: str) -> None:
    assert normalize_full_name(variant) == normalize_full_name("Соколова Алёна Викторовна")
    assert normalize_full_name(variant) == "соколова алена викторовна"


@pytest.mark.parametrize(
    "other", ["Соколова Алёна", "Соколова Алина Викторовна", "Соколова Алёна Викторовна-Орлова"]
)
def test_full_name_must_match_completely(other: str) -> None:
    assert normalize_full_name(other) != normalize_full_name("Соколова Алёна Викторовна")


@pytest.mark.parametrize(
    "inn",
    [p.name for p in FIXTURES.iterdir() if p.is_dir()]
    + [u.person_inn for u in DEMO_USERS if u.person_inn],
)
def test_demo_inns_are_valid(inn: str) -> None:
    assert is_valid_inn(inn)


@pytest.mark.parametrize(
    "inn", ["0099020011", "009903001041", "009903001050", "123", "00990200١٠", "abcdefghij"]
)
def test_invalid_inns(inn: str) -> None:
    assert not is_valid_inn(inn)


def _record(inn: str) -> RegistryRecord:
    from pydantic import TypeAdapter

    return TypeAdapter(RegistryRecord).validate_python(registry(inn))


class _Applicant:
    def __init__(self, full_name: str, person_inn: str | None) -> None:
        self.full_name, self.person_inn = full_name, person_inn


def test_authorization_requires_inn_and_name() -> None:
    bakery = _record(BAKERY_INN)
    assert is_authorized_applicant(bakery, _Applicant("кузнецова  анна михайловна", "009902001009"))
    assert not is_authorized_applicant(bakery, _Applicant("Кузнецова Анна Михайловна", None))
    assert not is_authorized_applicant(
        bakery, _Applicant("Кузнецова Анна Михайловна", "009902002059")
    )
    assert not is_authorized_applicant(
        bakery, _Applicant("Бухгалтерова Ольга Ивановна", "009902001009")
    )
    ie = _record(SOKOLOVA_INN)
    assert is_authorized_applicant(ie, _Applicant("Соколова Алена Викторовна", SOKOLOVA_INN))


# --- Тексты согласий -------------------------------------------------------------------


CONSENTS = Path(__file__).resolve().parents[1] / "app" / "onboarding" / "consents"
EXPECTED_TEXTS = [
    {"type": kind, "version": version, "text": (CONSENTS / f"{version}.md").read_text().strip()}
    for kind, version in (("PD_PROCESSING", "pd-v1"), ("BKI_REQUEST", "bki-v1"))
]


async def test_consent_texts_come_from_files(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/v1/consents/texts")
    assert response.status_code == 200
    assert response.json() == EXPECTED_TEXTS


# --- Ветки company-binding -------------------------------------------------------------


async def test_binding_success_writes_everything_in_one_go(api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/v1/company", headers=bearer(BAKERY_DIRECTOR))).json()["error"][
        "code"
    ] == "COMPANY_NOT_BOUND"
    response = await bind(api, BAKERY_DIRECTOR, BAKERY_INN)
    assert response.status_code == 200, response.text
    company = response.json()
    assert company["inn"] == BAKERY_INN
    assert company["legal_form"] == "LLC"
    assert company["name"] == "ООО «Пекарня Плюс»"
    assert company["okved_main"] == "10.71"
    assert company["registered_at"] == "2023-10-21"
    assert db_counts() == {
        "companies": 1,
        "consents": 1,
        "external_snapshots": 1,
        "bound_users": 1,
    }
    me = (await api.get("/api/v1/auth/me", headers=bearer(BAKERY_DIRECTOR))).json()
    assert me["company_id"] == company["id"]
    assert (await api.get("/api/v1/company", headers=bearer(BAKERY_DIRECTOR))).json() == company

    engine = sa.create_engine(TEST_DATABASE_URL)
    with engine.connect() as conn:
        consent = conn.execute(sa.text("SELECT type, text_version, application_id FROM consents"))
        assert consent.one() == ("PD_PROCESSING", "pd-v1", None)
        snapshot = conn.execute(sa.text("SELECT provider, response_json FROM external_snapshots"))
        assert snapshot.one() == ("EGRUL", registry(BAKERY_INN))
    engine.dispose()


async def test_repeat_binding_is_200_without_new_rows(api: httpx.AsyncClient) -> None:
    first = await bind(api, BAKERY_DIRECTOR, BAKERY_INN)
    again = await bind(api, BAKERY_DIRECTOR, BAKERY_INN)
    assert again.status_code == 200
    assert again.json() == first.json()
    assert db_counts()["consents"] == db_counts()["external_snapshots"] == 1


async def test_ie_binding(api: httpx.AsyncClient) -> None:
    response = await bind(api, SOKOLOVA, SOKOLOVA_INN)
    assert response.status_code == 200, response.text
    assert response.json()["legal_form"] == "IE"
    assert response.json()["name"] == "ИП Соколова А. В."


@pytest.mark.parametrize(
    ("login", "inn", "version", "status", "code"),
    [
        (BAKERY_DIRECTOR, "0099020011", "pd-v1", 422, "INVALID_INN"),
        (BAKERY_DIRECTOR, "009902001008", "pd-v1", 422, "INVALID_INN"),
        (BAKERY_DIRECTOR, "12345", "pd-v1", 422, "VALIDATION_ERROR"),  # формат — схема контракта
        (BAKERY_DIRECTOR, BAKERY_INN, "pd-v0", 422, "CONSENT_REQUIRED"),
        (BAKERY_DIRECTOR, BAKERY_INN, "bki-v1", 422, "CONSENT_REQUIRED"),
        (BAKERY_DIRECTOR, "7707083893", "pd-v1", 422, "COMPANY_NOT_IN_REGISTRY"),
        (ACCOUNTANT, BAKERY_INN, "pd-v1", 403, "APPLICANT_NOT_AUTHORIZED"),
        (TECH_DIRECTOR, BAKERY_INN, "pd-v1", 403, "APPLICANT_NOT_AUTHORIZED"),
        (MANAGER_LOGIN, BAKERY_INN, "pd-v1", 403, "FORBIDDEN"),
    ],
)
async def test_binding_errors(
    api: httpx.AsyncClient, login: str, inn: str, version: str, status: int, code: str
) -> None:
    response = await bind(api, login, inn, version)
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code
    assert db_counts()["companies"] == 0


async def test_check_order_inn_before_consent(api: httpx.AsyncClient) -> None:
    response = await bind(api, BAKERY_DIRECTOR, "0099020011", "pd-v0")
    assert response.json()["error"]["code"] == "INVALID_INN"


async def test_registry_unavailable_is_503(api: httpx.AsyncClient, sim: respx.MockRouter) -> None:
    sim.get(f"/egrul/v1/companies/{BAKERY_INN}").respond(503)
    response = await bind(api, BAKERY_DIRECTOR, BAKERY_INN)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert db_counts()["companies"] == 0


async def test_liquidated_company_can_be_bound(
    api: httpx.AsyncClient, sim: respx.MockRouter
) -> None:
    sim.get(f"/egrul/v1/companies/{BAKERY_INN}").respond(
        200, json={**registry(BAKERY_INN), "status": "LIQUIDATED"}
    )
    assert (await bind(api, BAKERY_DIRECTOR, BAKERY_INN)).status_code == 200


async def test_user_already_bound(api: httpx.AsyncClient, sim: respx.MockRouter) -> None:
    # Директор, который руководит двумя компаниями: вторая привязка запрещена.
    second = {**registry(TECH_INN), "director": registry(BAKERY_INN)["director"]}
    sim.get(f"/egrul/v1/companies/{TECH_INN}").respond(200, json=second)
    assert (await bind(api, BAKERY_DIRECTOR, BAKERY_INN)).status_code == 200
    response = await bind(api, BAKERY_DIRECTOR, TECH_INN)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "USER_ALREADY_BOUND"
    assert db_counts()["companies"] == 1


def _add_twin(login: str = "twin.bakery@creditflow.demo") -> str:
    """Вторая учётка с теми же ФИО и ИНН, что у директора «Пекарни Плюс»: оба проходят
    сверку полномочий, и уникальность проверяется именно привязкой."""
    engine = sa.create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO users (id, role, email, password_hash, full_name, person_inn) "
                "VALUES (:id, 'CLIENT', :email, 'x', 'Кузнецова Анна Михайловна', '009902001009')"
            ),
            {"id": uuid.uuid5(uuid.NAMESPACE_URL, login), "email": login},
        )
    engine.dispose()
    return login


async def test_company_already_bound(api: httpx.AsyncClient) -> None:
    twin = _add_twin()
    assert (await bind(api, BAKERY_DIRECTOR, BAKERY_INN)).status_code == 200
    response = await bind(api, twin, BAKERY_INN)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "COMPANY_ALREADY_BOUND"


@pytest.fixture
def twin(api: httpx.AsyncClient) -> str:
    return _add_twin()


@pytest.fixture
def barrier(api: httpx.AsyncClient) -> Iterator[None]:
    """Оба запроса проходят реестр и входят в транзакцию одновременно."""
    original = ExtSimClient.get_registry_record
    gate = asyncio.Barrier(2)

    async def synchronized(self: ExtSimClient, inn: str, **kwargs: Any) -> RegistryRecord:
        record = await original(self, inn, **kwargs)
        await gate.wait()
        return record

    ExtSimClient.get_registry_record = synchronized  # type: ignore[method-assign]
    yield
    ExtSimClient.get_registry_record = original  # type: ignore[method-assign]


@pytest.mark.parametrize("company_exists", [False, True])
async def test_concurrent_binding_of_one_inn_by_two_users(
    api: httpx.AsyncClient, twin: str, barrier: None, company_exists: bool
) -> None:
    if company_exists:
        # Компания уже есть (например, из демо-seed), но ни к кому не привязана: уникальный
        # INSERT здесь не сериализует транзакции, это делает только блокировка строки.
        engine = sa.create_engine(TEST_DATABASE_URL)
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO companies (inn, legal_form, name, okved_main, registered_at) "
                    "VALUES (:inn, 'LLC', 'ООО «Пекарня Плюс»', '10.71', '2023-10-21')"
                ),
                {"inn": BAKERY_INN},
            )
        engine.dispose()
    first, second = await asyncio.gather(
        bind(api, BAKERY_DIRECTOR, BAKERY_INN), bind(api, twin, BAKERY_INN)
    )
    assert sorted([first.status_code, second.status_code]) == [200, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["error"]["code"] == "COMPANY_ALREADY_BOUND"
    assert db_counts() == {
        "companies": 1,
        "consents": 1,
        "external_snapshots": 1,
        "bound_users": 1,
    }


async def test_concurrent_repeat_binding_by_same_user(
    api: httpx.AsyncClient, barrier: None
) -> None:
    first, second = await asyncio.gather(
        bind(api, BAKERY_DIRECTOR, BAKERY_INN), bind(api, BAKERY_DIRECTOR, BAKERY_INN)
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert db_counts() == {
        "companies": 1,
        "consents": 1,
        "external_snapshots": 1,
        "bound_users": 1,
    }
