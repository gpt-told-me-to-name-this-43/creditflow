"""Тестовый reset и демо-состояние (#7): clean, demo, повторяемость, защита токеном."""

import time
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from tests.applications.conftest import MANAGER, AsUser, Manager, count

TOKEN = "r" * 32


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(
        demo_auth_enabled=True,
        app_as_of_date=date(2026, 10, 21),
        test_reset_enabled=True,
        test_reset_token=TOKEN,
    )


async def reset(api: httpx.AsyncClient, mode: str, token: str | None = TOKEN) -> httpx.Response:
    headers = {"X-Test-Reset-Token": token} if token else {}
    return await api.post("/_test/reset", params={"mode": mode}, headers=headers)


async def snapshot(db: AsyncEngine) -> dict[str, Any]:
    async with db.connect() as conn:
        apps = (
            await conn.execute(
                sa.text(
                    "SELECT c.inn, a.status, a.revision, a.requested_amount_rub "
                    "FROM applications a "
                    "JOIN companies c ON c.id = a.company_id ORDER BY 1, 2, 3, 4"
                )
            )
        ).all()
        contracts = (await conn.execute(sa.text("SELECT number FROM contracts ORDER BY 1"))).all()
    tables = (
        "users",
        "companies",
        "credit_products",
        "scoring_results",
        "credit_decisions",
        "offers",
    )
    return {
        "apps": [tuple(map(str, a)) for a in apps],
        "contracts": [c[0] for c in contracts],
        **{t: await count(db, t) for t in tables},
    }


async def test_clean_reset_leaves_only_base_seed(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    response = await reset(api, "clean")
    assert response.status_code == 200 and response.json() == {"mode": "clean"}
    snap = await snapshot(db)
    assert (snap["users"], snap["credit_products"], snap["companies"], snap["apps"]) == (
        10,
        2,
        0,
        [],
    )


async def test_demo_reset_state(api: httpx.AsyncClient, db: AsyncEngine, as_user: AsUser) -> None:
    started = time.perf_counter()
    response = await reset(api, "demo")
    assert response.status_code == 200, response.text
    assert time.perf_counter() - started < 30
    async with db.connect() as conn:
        current: dict[str, str | None] = dict(
            (
                await conn.execute(
                    sa.text(
                        "SELECT DISTINCT ON (c.inn) c.inn, a.status FROM companies c "
                        "LEFT JOIN applications a ON a.company_id = c.id "
                        "ORDER BY c.inn, a.created_at DESC"
                    )
                )
            ).all()
        )
        c1_issued = await conn.scalar(
            sa.text(
                "SELECT count(*) FROM applications a JOIN companies c ON c.id = a.company_id "
                "WHERE c.inn = '0099010012' AND a.status = 'ISSUED'"
            )
        )
        decided = await conn.scalar(
            sa.text("SELECT count(DISTINCT application_id) FROM credit_decisions")
        )
    # C2 и C4 — путь с нуля через онбординг #5: компании нет, пока клиент не привяжет ИНН.
    assert current == {
        "0099010012": "REJECTED",  # C1: последняя прошлая заявка; новую подать можно
        "009903001040": "NEED_INFO",
        "0099050015": "REJECTED",
        "0099060013": "UNDER_REVIEW",
        "009907001027": "UNDER_REVIEW",
    }
    assert c1_issued == 2
    manager = Manager(api, await as_user(MANAGER))  # reset пересоздал учётки — новый токен
    assert decided and decided >= 9
    queue = (
        await api.get(
            "/manager/applications", params={"status": "UNDER_REVIEW"}, headers=manager.headers
        )
    ).json()
    assert {(q["company_inn"], q["suggested_action"]) for q in queue} == {
        ("0099060013", "BLOCKED_BY_RULE"),
        ("009907001027", "MANUAL_REVIEW"),
    }
    stats = (await api.get("/manager/stats", headers=manager.headers)).json()
    assert stats["median_time_to_decision_seconds"] and stats["decisions_matching_suggestion_share"]


async def test_two_demo_resets_give_same_state(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    assert (await reset(api, "demo")).status_code == 200
    first = await snapshot(db)
    assert (await reset(api, "demo")).status_code == 200
    assert await snapshot(db) == first
    assert first["contracts"][0] == "CF-2026-000001"


async def test_reset_without_token_is_404(api: httpx.AsyncClient, db: AsyncEngine) -> None:
    before = await count(db, "users")
    response = await reset(api, "clean", token=None)
    assert response.status_code == 404
    assert await count(db, "users") == before
