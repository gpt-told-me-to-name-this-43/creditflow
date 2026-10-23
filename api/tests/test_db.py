"""Модель данных (issue #6): roundtrip миграций, insert-only триггеры, идемпотентный seed."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from app import seed
from app.core.db import create_engine

from .conftest import TEST_DATABASE_URL

API_DIR = Path(__file__).resolve().parents[1]
FIXTURES = API_DIR.parent / "ext-sim" / "fixtures"
SYNC_URL = TEST_DATABASE_URL  # psycopg 3 поддерживает и sync, и async


@pytest.fixture
def alembic_config(monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.chdir(API_DIR)
    return Config(str(API_DIR / "alembic.ini"))


@pytest.fixture
def db(alembic_config: Config) -> Iterator[sa.Connection]:
    command.upgrade(alembic_config, "head")
    engine = sa.create_engine(SYNC_URL)
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def test_migrations_roundtrip(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)  # модели и миграции не разошлись


@pytest.mark.parametrize(
    "statement", ["UPDATE scoring_results SET score = 99", "DELETE FROM scoring_results"]
)
def test_scoring_results_is_insert_only(db: sa.Connection, statement: str) -> None:
    seeded = db.execute(
        sa.text("""
        WITH c AS (INSERT INTO companies (inn, legal_form, name, okved_main, registered_at)
                   VALUES ('0099777001', 'LLC', 'ООО «Тест»', '62.01', '2020-01-01') RETURNING id),
             u AS (INSERT INTO users (role, email, password_hash, full_name)
                   VALUES ('CLIENT', 'trigger@test', 'x', 'Тест') RETURNING id),
             a AS (INSERT INTO applications (company_id, owner_user_id)
                   SELECT c.id, u.id FROM c, u RETURNING id)
        INSERT INTO scoring_results (application_id, kind, inputs_json, inputs_hash, engine_version,
                                     calculation_status)
        SELECT id, 'SUBMISSION', '{}'::jsonb, 'h', 'risk-1.0.0', 'SKIPPED' FROM a RETURNING id
    """)
    ).scalar_one()
    assert seeded
    with pytest.raises(sa.exc.DBAPIError, match="insert-only"):
        db.execute(sa.text(statement))
    db.rollback()  # ничего из теста не остаётся в БД


async def test_seed_twice_gives_exact_counts(db: sa.Connection) -> None:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        for _ in range(2):
            async with engine.begin() as conn:
                await seed.run_base_seed(conn)
    finally:
        await engine.dispose()
    emails = [u.email for u in seed.DEMO_USERS]
    users = db.execute(sa.text("SELECT count(*) FROM users WHERE email = ANY(:e)"), {"e": emails})
    assert users.scalar_one() == 10
    products = db.execute(sa.text("SELECT id FROM credit_products ORDER BY id")).scalars().all()
    assert products == ["investment", "working_capital"]


def test_directors_match_registry_fixtures() -> None:
    """Учётки директоров совпадают с ЕГРЮЛ/ЕГРИП ext-sim, иначе привязка по ИНН вернёт 403."""
    registry = {}
    for path in FIXTURES.glob("*/egr*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        person = record.get("director") or {"full_name": record["full_name"], "inn": record["inn"]}
        registry[person["inn"]] = person["full_name"]
    directors = [u for u in seed.DEMO_USERS if u.email.startswith(("director.", "ip."))]
    assert len(directors) == 7
    for user in directors:
        assert registry.get(user.person_inn or "") == user.full_name, user.email
    accountant = next(u for u in seed.DEMO_USERS if u.email.startswith("accountant."))
    assert accountant.person_inn not in registry  # бухгалтер не руководитель ни одной компании
