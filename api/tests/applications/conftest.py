"""Интеграционные фикстуры конвейера (#7): живой PostgreSQL, приложение с lifespan по ASGI.

- БД на каждый тест приводится к базовому seed: заявки, компании и всё связанное
  удаляются, продукты и демо-учётки остаются (argon2-хеширование seed — один раз).
- `api` — `httpx.AsyncClient` поверх ASGI с настоящим lifespan: каждый запрос получает
  собственную сессию и соединение, поэтому `asyncio.gather` даёт настоящую конкуренцию.
- `as_user(email)` — заголовок с JWT демо-учётки; `bind_company(email, inn)` — привязка
  по фикстуре ext-sim (до #5 — напрямую в БД).
"""

import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from alembic import command
from app import seed
from app.core.config import Settings
from app.core.db import create_engine
from app.core.security import encode_token
from app.extsim_client import ExtSimClient
from app.main import create_app
from app.schemas.auth import Role
from tests.applications.extsim_fake import FakeExtSim
from tests.conftest import EXT_SIM_URL, REPO_ROOT, TEST_DATABASE_URL, TEST_SECRET_KEY

API_DIR = REPO_ROOT / "api"
EXT_SIM_FIXTURES = REPO_ROOT / "ext-sim" / "fixtures"

BAKERY = "director.bakery@creditflow.demo"  # C2, «Пекарня Плюс»
BAKERY_INN = "0099020010"
TECHSERVICE = "director.techservice@creditflow.demo"  # C1
TECHSERVICE_INN = "0099010012"
MANAGER = "manager.anna@creditflow.demo"

# Всё, кроме users и credit_products: TRUNCATE не вызывает insert-only триггеры (они на DELETE).
_TRUNCATE = (
    "ai_feedback, ai_reports, sign_challenges, contracts, info_requests, offers, "
    "credit_decisions, decision_proposals, application_events, idempotency_keys, "
    "account_transactions, external_snapshots, consents, scoring_results, applications"
)

AsUser = Callable[[str], Awaitable[dict[str, str]]]
BindCompany = Callable[[str, str], Awaitable[None]]


@pytest.fixture
def migrated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.chdir(API_DIR)
    command.upgrade(Config(str(API_DIR / "alembic.ini")), "head")
    yield


@pytest.fixture
async def db(migrated: None) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(sa.text("UPDATE users SET company_id = NULL"))
        await conn.execute(sa.text(f"TRUNCATE {_TRUNCATE}"))
        await conn.execute(sa.text("DELETE FROM companies"))
        emails = [u.email for u in seed.DEMO_USERS]
        await conn.execute(sa.text("DELETE FROM users WHERE email <> ALL(:e)"), {"e": emails})
        for u in seed.DEMO_USERS:  # тесты меняют ФИО (смена руководителя) — возвращаем seed
            await conn.execute(
                sa.text("UPDATE users SET full_name = :n, person_inn = :i WHERE email = :e"),
                {"n": u.full_name, "i": u.person_inn, "e": u.email},
            )
        known = await conn.scalar(
            sa.text("SELECT count(*) FROM users WHERE email = ANY(:e)"), {"e": emails}
        )
        if known != len(emails):
            await seed.run_base_seed(conn)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(demo_auth_enabled=True, app_as_of_date=date(2026, 10, 21))


@pytest.fixture
def ext_sim() -> FakeExtSim:
    return FakeExtSim()


@pytest.fixture
async def app(db: AsyncEngine, settings: Settings, ext_sim: FakeExtSim) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    application.state.recovery_interval = None  # восстановление тесты вызывают явно
    async with application.router.lifespan_context(application):
        application.state.disburse_delay = (0.0, 0.0)
        await application.state.ext_sim.aclose()
        application.state.ext_sim = ExtSimClient(
            EXT_SIM_URL, transport=ext_sim.transport(), retry_delay=0
        )
        yield application


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api.test/api/v1") as c:
        yield c


@pytest.fixture
def as_user(db: AsyncEngine) -> AsUser:
    async def headers(email: str) -> dict[str, str]:
        async with db.connect() as conn:
            row = (
                await conn.execute(
                    sa.text("SELECT id, role FROM users WHERE email = :e"), {"e": email}
                )
            ).one()
        token = encode_token(row.id, Role(row.role), TEST_SECRET_KEY)
        return {"Authorization": f"Bearer {token}"}

    return headers


def registry_record(inn: str) -> dict[str, str]:
    """Компания из фикстуры ext-sim: ЕГРЮЛ (10 цифр) или ЕГРИП (12 цифр)."""
    folder = EXT_SIM_FIXTURES / inn
    if len(inn) == 10:
        data = json.loads((folder / "egrul.json").read_text(encoding="utf-8"))
        return {"legal_form": "LLC", "name": data["name"], **_common(data)}
    data = json.loads((folder / "egrip.json").read_text(encoding="utf-8"))
    return {"legal_form": "IE", "name": f"ИП {data['full_name']}", **_common(data)}


def _common(data: dict[str, str]) -> dict[str, str]:
    return {
        "inn": data["inn"],
        "okved_main": data["okved_main"],
        "registered_at": data["registered_at"],
    }


@pytest.fixture
def bind_company(db: AsyncEngine) -> BindCompany:
    async def bind(email: str, inn: str) -> None:
        company = registry_record(inn)
        async with db.begin() as conn:
            company_id = await conn.scalar(
                sa.text(
                    "INSERT INTO companies (inn, legal_form, name, okved_main, registered_at) "
                    "VALUES (:inn, :legal_form, :name, :okved_main, CAST(:registered_at AS date)) "
                    "RETURNING id"
                ),
                company,
            )
            await conn.execute(
                sa.text("UPDATE users SET company_id = :c WHERE email = :e"),
                {"c": company_id, "e": email},
            )

    return bind


@pytest.fixture
async def bakery(as_user: AsUser, bind_company: BindCompany) -> dict[str, str]:
    """Заголовки C2 с привязанной «Пекарней Плюс»."""
    await bind_company(BAKERY, BAKERY_INN)
    return await as_user(BAKERY)


async def count(db: AsyncEngine, table: str) -> int:
    async with db.connect() as conn:
        value = await conn.scalar(sa.text(f"SELECT count(*) FROM {table}"))
    return int(value or 0)


@dataclass(frozen=True)
class DemoCompany:
    """Компания C1–C7/T1 и её запрос из docs/demo-data.md §6."""

    code: str
    email: str
    inn: str
    product_id: str
    purpose_code: str
    amount: int
    term: int

    @property
    def terms(self) -> dict[str, object]:
        return {
            "purpose_code": self.purpose_code,
            "requested_amount_rub": self.amount,
            "term_months": self.term,
            "product_id": self.product_id,
        }


T1_EMAIL = "director.t1@creditflow.test"
COMPANIES = {
    c.code: c
    for c in (
        DemoCompany("C1", TECHSERVICE, TECHSERVICE_INN, "investment", "EQUIPMENT", 2_000_000, 36),
        DemoCompany("C2", BAKERY, BAKERY_INN, "investment", "EQUIPMENT", 3_000_000, 36),
        DemoCompany(
            "C3",
            "ip.sokolova@creditflow.demo",
            "009903001040",
            "working_capital",
            "INVENTORY",
            800_000,
            12,
        ),
        DemoCompany(
            "C4",
            "director.newstart@creditflow.demo",
            "0099040017",
            "investment",
            "EQUIPMENT",
            500_000,
            24,
        ),
        DemoCompany(
            "C5",
            "director.vector@creditflow.demo",
            "0099050015",
            "working_capital",
            "SUPPLIERS",
            1_000_000,
            12,
        ),
        DemoCompany(
            "C6",
            "director.sklad@creditflow.demo",
            "0099060013",
            "working_capital",
            "WORKING_CAPITAL",
            1_500_000,
            18,
        ),
        DemoCompany(
            "C7",
            "ip.orlov@creditflow.demo",
            "009907001027",
            "investment",
            "RENOVATION",
            1_000_000,
            36,
        ),
        DemoCompany("T1", T1_EMAIL, "0099990019", "investment", "EQUIPMENT", 1_000_000, 36),
    )
}


class Pipeline:
    """Клиентские шаги конвейера через HTTP: черновик → условия → submit."""

    def __init__(
        self, api: httpx.AsyncClient, as_user: AsUser, bind_company: BindCompany, db: AsyncEngine
    ) -> None:
        self.api, self.as_user, self.bind_company, self.db = api, as_user, bind_company, db

    async def client(self, code: str) -> dict[str, str]:
        company = COMPANIES[code]
        if code == "T1":  # учётки T1 нет в seed: руководитель из фикстуры, только тесты
            async with self.db.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO users (role, email, password_hash, full_name, person_inn) "
                        "VALUES ('CLIENT', :e, 'x', 'Тестов Тест Тестович', '009999001063') "
                        "ON CONFLICT (email) DO NOTHING"
                    ),
                    {"e": T1_EMAIL},
                )
        await self.bind_company(company.email, company.inn)
        return await self.as_user(company.email)

    async def draft(self, code: str) -> tuple[dict[str, str], dict[str, Any]]:
        """Привязанный клиент и заполненный черновик (revision = 2)."""
        headers = await self.client(code)
        created = await self.api.post("/applications", json={}, headers=headers)
        app_id = created.json()["id"]
        patched = await self.api.patch(
            f"/applications/{app_id}",
            json={"revision": 1, **COMPANIES[code].terms},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
        result: dict[str, Any] = patched.json()
        return headers, result

    async def submit(
        self,
        headers: dict[str, str],
        app_id: object,
        revision: object,
        key: str | None = None,
        consent: str = "bki-v1",
    ) -> httpx.Response:
        return await self.api.post(
            f"/applications/{app_id}/submit",
            json={"revision": revision, "bki_consent_version": consent},
            headers={**headers, "Idempotency-Key": key or str(uuid.uuid4())},
        )

    async def submitted(self, code: str) -> tuple[dict[str, str], dict[str, Any]]:
        headers, draft = await self.draft(code)
        response = await self.submit(headers, draft["id"], draft["revision"])
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return headers, result


@pytest.fixture
def pipeline(
    api: httpx.AsyncClient, as_user: AsUser, bind_company: BindCompany, db: AsyncEngine
) -> Pipeline:
    return Pipeline(api, as_user, bind_company, db)


class Manager:
    """Шаги менеджера через HTTP."""

    def __init__(self, api: httpx.AsyncClient, headers: dict[str, str]) -> None:
        self.api, self.headers = api, headers

    async def card(self, app_id: object) -> dict[str, Any]:
        response = await self.api.get(f"/manager/applications/{app_id}", headers=self.headers)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    async def decide(
        self, app_id: object, revision: object, key: str | None = None, **body: Any
    ) -> httpx.Response:
        return await self.api.post(
            f"/manager/applications/{app_id}/decisions",
            json={"revision": revision, **body},
            headers={**self.headers, "Idempotency-Key": key or str(uuid.uuid4())},
        )

    async def preview(self, app_id: object, amount: int, term: int) -> httpx.Response:
        return await self.api.post(
            f"/manager/applications/{app_id}/offer-preview",
            json={"amount_rub": amount, "term_months": term},
            headers=self.headers,
        )


@pytest.fixture
async def manager(api: httpx.AsyncClient, as_user: AsUser) -> Manager:
    return Manager(api, await as_user(MANAGER))


@pytest.fixture
async def manager2(api: httpx.AsyncClient, as_user: AsUser) -> Manager:
    return Manager(api, await as_user("manager.oleg@creditflow.demo"))


async def row_counts(db: AsyncEngine) -> dict[str, int]:
    tables = [*_TRUNCATE.replace(" ", "").split(","), "companies", "users"]
    return {t: await count(db, t) for t in tables}


def client_keys_only(body: dict[str, Any]) -> None:
    """Клиентский ответ — ровно поля ClientApplicationView, без внутренних."""
    from app.schemas.client import ClientApplicationView

    assert set(body) == set(ClientApplicationView.model_fields)
