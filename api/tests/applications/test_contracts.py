"""Договор, подписание кодом из UI и смоделированная выдача (#7): C1 до ISSUED, M12, challenge."""

import logging
import re
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from app.contracts.service import recover_pending_disbursements
from tests.applications.conftest import Manager, Pipeline, client_keys_only, count


async def approved(
    pipeline: Pipeline, manager: Manager, code: str = "C1"
) -> tuple[dict[str, str], str, int]:
    headers, body = await pipeline.submitted(code)
    decided = await manager.decide(body["id"], body["revision"], action="APPROVE", comment="ok")
    assert decided.status_code == 201, decided.text
    return headers, body["id"], decided.json()["revision"]


async def challenge(
    api: httpx.AsyncClient, headers: dict[str, str], app_id: str, revision: int
) -> httpx.Response:
    return await api.post(
        f"/applications/{app_id}/sign/challenge", json={"revision": revision}, headers=headers
    )


async def sign(
    api: httpx.AsyncClient, headers: dict[str, str], app_id: str, revision: int, ch: str, code: str
) -> httpx.Response:
    return await api.post(
        f"/applications/{app_id}/sign",
        json={"revision": revision, "challenge_id": ch, "code": code},
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"


async def test_c1_full_path_to_issued(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    contract = (await api.get(f"/applications/{app_id}/contract", headers=headers)).json()
    assert re.fullmatch(r"CF-2026-\d{6}", contract["number"])
    assert (contract["status"], contract["amount_rub"], contract["term_months"]) == (
        "DRAFT",
        "2000000.00",
        36,
    )
    assert contract["monthly_payment_rub"] == "78465.71"
    assert contract["account_masked"] == "40702 •••• 0012"
    assert "## Основные условия" in contract["key_terms_markdown"]

    ch = (await challenge(api, headers, app_id, revision)).json()
    assert ch["revision"] == revision + 1 and ch["attempts_remaining"] == 3
    assert re.fullmatch(r"\d{6}", ch["demo_code"])
    signed = await sign(api, headers, app_id, ch["revision"], ch["challenge_id"], ch["demo_code"])
    assert signed.status_code == 200, signed.text
    client_keys_only(signed.json())
    assert signed.json()["status"] == "SIGNED"

    # BackgroundTasks выполнились после ответа (в тестах без паузы 3–5 с)
    view = (await api.get(f"/applications/{app_id}", headers=headers)).json()
    assert view["status"] == "ISSUED"
    assert view["timeline"][-1]["from_status"] == "SIGNED"
    async with db.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT c.status, c.issued_at IS NOT NULL AS issued, e.actor_user_id "
                    "FROM contracts c JOIN application_events e ON e.to_status = 'ISSUED'"
                )
            )
        ).one()
    assert (row.status, row.issued, row.actor_user_id) == ("ISSUED", True, None)  # SYSTEM
    repeat = await sign(api, headers, app_id, view["revision"], ch["challenge_id"], ch["demo_code"])
    assert repeat.status_code == 409


async def test_three_wrong_codes_close_challenge(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    ch = (await challenge(api, headers, app_id, revision)).json()
    bad = wrong(ch["demo_code"])
    results = [
        await sign(api, headers, app_id, ch["revision"], ch["challenge_id"], bad) for _ in range(3)
    ]
    assert [r.status_code for r in results] == [422, 422, 429]
    assert [r.json()["error"]["details"] for r in results] == [
        {"remaining_attempts": 2},
        {"remaining_attempts": 1},
        {"scope": "SIGN_ATTEMPTS"},
    ]
    assert "Retry-After" not in results[2].headers
    closed = await sign(api, headers, app_id, ch["revision"], ch["challenge_id"], ch["demo_code"])
    assert closed.status_code == 422
    assert closed.json()["error"]["code"] == "SIGN_CHALLENGE_EXPIRED"
    async with db.connect() as conn:  # неудачные попытки не меняют revision
        assert await conn.scalar(sa.text("SELECT revision FROM applications")) == ch["revision"]
    fresh = (await challenge(api, headers, app_id, ch["revision"])).json()
    ok = await sign(
        api, headers, app_id, fresh["revision"], fresh["challenge_id"], fresh["demo_code"]
    )
    assert ok.status_code == 200


async def test_new_challenge_invalidates_previous_and_stores_only_hash(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    first = (await challenge(api, headers, app_id, revision)).json()
    second = (await challenge(api, headers, app_id, first["revision"])).json()
    old = await sign(
        api, headers, app_id, second["revision"], first["challenge_id"], first["demo_code"]
    )
    assert old.status_code == 422 and old.json()["error"]["code"] == "SIGN_CHALLENGE_EXPIRED"
    async with db.connect() as conn:
        hashes = (
            (await conn.execute(sa.text("SELECT code_hash FROM sign_challenges"))).scalars().all()
        )
    assert all(len(h) == 64 and h not in {first["demo_code"], second["demo_code"]} for h in hashes)


async def test_expired_challenge(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    ch = (await challenge(api, headers, app_id, revision)).json()
    async with db.begin() as conn:
        await conn.execute(
            sa.text("UPDATE sign_challenges SET expires_at = now() - interval '1 second'")
        )
    response = await sign(api, headers, app_id, ch["revision"], ch["challenge_id"], ch["demo_code"])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SIGN_CHALLENGE_EXPIRED"


async def test_challenge_rate_limit(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    for _ in range(5):
        response = await challenge(api, headers, app_id, revision)
        assert response.status_code == 200
        revision = response.json()["revision"]
    limited = await challenge(api, headers, app_id, revision)
    assert limited.status_code == 429
    details = limited.json()["error"]["details"]
    assert details["scope"] == "CHALLENGE_ISSUE"
    assert limited.headers["Retry-After"] == str(details["retry_after_seconds"])


async def test_demo_code_only_in_demo_mode(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, app: FastAPI
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    app.state.settings = app.state.settings.model_copy(update={"demo_auth_enabled": False})
    body = (await challenge(api, headers, app_id, revision)).json()
    assert "demo_code" not in body


async def test_code_is_never_logged(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    headers, app_id, revision = await approved(pipeline, manager)
    with caplog.at_level(logging.DEBUG):
        ch = (await challenge(api, headers, app_id, revision)).json()
        await sign(api, headers, app_id, ch["revision"], ch["challenge_id"], ch["demo_code"])
    assert ch["demo_code"] not in caplog.text


async def test_contract_404_before_approval(pipeline: Pipeline, api: httpx.AsyncClient) -> None:
    headers, body = await pipeline.submitted("C1")
    response = await api.get(f"/applications/{body['id']}/contract", headers=headers)
    assert response.status_code == 404


async def test_challenge_outside_approved_is_409(
    pipeline: Pipeline, api: httpx.AsyncClient
) -> None:
    headers, body = await pipeline.submitted("C1")
    response = await challenge(api, headers, body["id"], body["revision"])
    assert response.status_code == 409


async def test_restart_in_signed_is_recovered(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient, db: AsyncEngine, app: FastAPI
) -> None:
    headers, app_id, _ = await approved(pipeline, manager)
    async with db.begin() as conn:  # «процесс упал» между COMMIT подписания и выдачей
        await conn.execute(sa.text("UPDATE applications SET status = 'SIGNED'"))
        await conn.execute(
            sa.text(
                "UPDATE contracts SET status = 'SIGNED', signed_at = now() - interval '11 seconds'"
            )
        )
    assert await recover_pending_disbursements(app.state.sessionmaker) == 1
    assert await recover_pending_disbursements(app.state.sessionmaker) == 0  # идемпотентно
    view = (await api.get(f"/applications/{app_id}", headers=headers)).json()
    assert view["status"] == "ISSUED"
    # создание, submit, APPROVE, выдача (SIGNED выставлен в обход API)
    assert await count(db, "application_events") == 4


async def test_fresh_signed_is_not_recovered_early(
    pipeline: Pipeline, manager: Manager, db: AsyncEngine, app: FastAPI
) -> None:
    await approved(pipeline, manager)
    async with db.begin() as conn:
        await conn.execute(sa.text("UPDATE applications SET status = 'SIGNED'"))
        await conn.execute(sa.text("UPDATE contracts SET status = 'SIGNED', signed_at = now()"))
    assert await recover_pending_disbursements(app.state.sessionmaker) == 0


async def test_m12_schedule_through_offer_contract(
    pipeline: Pipeline, manager: Manager, api: httpx.AsyncClient
) -> None:
    headers, body = await pipeline.submitted("C2")
    await manager.decide(
        body["id"],
        3,
        action="COUNTER_OFFER",
        amount_rub=2_340_000,
        client_reason_code="HIGH_DEBT_LOAD",
        comment="Лимит на 36 мес.",
    )
    view = (await api.get(f"/applications/{body['id']}", headers=headers)).json()
    await api.post(
        f"/applications/{body['id']}/offer/accept",
        json={"revision": view["revision"]},
        headers={**headers, "Idempotency-Key": "m12-accept"},
    )
    contract: dict[str, Any] = (
        await api.get(f"/applications/{body['id']}/contract", headers=headers)
    ).json()
    rows = contract["schedule"]
    assert len(rows) == 36
    assert {r["payment_rub"] for r in rows[:35]} == {"91804.88"}
    assert rows[-1]["payment_rub"] == "91804.63"
    assert sum(Decimal(r["interest_rub"]) for r in rows) == Decimal("964975.43")
    assert sum(Decimal(r["principal_rub"]) for r in rows) == Decimal("2340000.00")
    assert rows[-1]["balance_after_rub"] == "0.00"
    assert contract["overpayment_rub"] == "964975.43"
    assert rows[0]["due_date"] == "2026-11-21"
