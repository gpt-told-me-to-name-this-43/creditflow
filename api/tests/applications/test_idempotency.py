"""Idempotency-Key (#7, design §3.7): ровно один эффект, сохранённый ответ, ошибки не кешируются.

Настоящие маршруты с ключом (submit, decisions, …) появятся в следующих фазах, поэтому
здесь — тестовый маршрут с тем же контрактом: блокировка заявки, проверка revision,
эффект и `complete` в одной транзакции.
"""

import asyncio
import uuid
from datetime import timedelta
from typing import Any, Literal

import httpx
import pytest
import sqlalchemy as sa
from fastapi import APIRouter, FastAPI, status
from sqlalchemy.ext.asyncio import AsyncEngine

from app.applications import repo
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.idempotency import Idem, request_hash
from app.core.security import BoundClient
from app.schemas.common import ErrorCode, Schema
from tests.applications.conftest import (
    BAKERY,
    TECHSERVICE,
    TECHSERVICE_INN,
    AsUser,
    BindCompany,
    count,
)

Mode = Literal["ok", "slow", "fail_after_complete", "skip_complete", "steal"]


class Body(Schema):
    revision: int
    term_months: int
    mode: Mode = "ok"


router = APIRouter()


@router.post("/_idem/{application_id}", status_code=status.HTTP_201_CREATED)
async def effect(
    application_id: uuid.UUID, body: Body, user: BoundClient, session: DbSession, idem: Idem
) -> dict[str, Any]:
    async with session.begin():
        application = await repo.lock_owned(session, application_id, user.id)
        repo.ensure_revision(application, body.revision)
        if body.mode == "slow":
            await asyncio.sleep(0.2)
        application.term_months = body.term_months
        application.revision += 1
        result = {"revision": application.revision, "term_months": body.term_months}
        if body.mode == "skip_complete":
            return result
        if body.mode == "steal":  # запись перехвачена другим запросом как брошенная
            await session.execute(
                sa.text("UPDATE idempotency_keys SET created_at = clock_timestamp()")
            )
        await idem.complete(session, 201, result)
        if body.mode == "fail_after_complete":
            raise RuntimeError("сбой после complete, до COMMIT")
    return result


@pytest.fixture
async def client(app: FastAPI, api: httpx.AsyncClient, bakery: dict[str, str]) -> httpx.AsyncClient:
    app.include_router(router, prefix="/api/v1")
    api.headers.update(bakery)
    return api


@pytest.fixture
async def app_id(client: httpx.AsyncClient) -> str:
    response = await client.post("/applications", json={})
    assert response.status_code == 201
    value: str = response.json()["id"]
    return value  # revision = 1


async def call(
    client: httpx.AsyncClient, app_id: str, key: str | None, **body: Any
) -> httpx.Response:
    headers = {"Idempotency-Key": key} if key else {}
    return await client.post(f"/_idem/{app_id}", json=body, headers=headers)


async def revision(db: AsyncEngine) -> int:
    async with db.connect() as conn:
        return int(await conn.scalar(sa.text("SELECT revision FROM applications")) or 0)


async def keys(db: AsyncEngine) -> list[tuple[str, int | None]]:
    async with db.connect() as conn:
        rows = await conn.execute(sa.text("SELECT status, status_code FROM idempotency_keys"))
    return [(r.status, r.status_code) for r in rows]


def key() -> str:
    return str(uuid.uuid4())


async def test_repeat_returns_saved_response_without_second_effect(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    k = key()
    first = await call(client, app_id, k, revision=1, term_months=24)
    second = await call(client, app_id, k, revision=1, term_months=24)
    assert (first.status_code, second.status_code) == (201, 201)
    assert second.json() == first.json() == {"revision": 2, "term_months": 24}
    assert await revision(db) == 2
    assert await keys(db) == [("COMPLETED", 201)]


async def test_body_key_order_does_not_matter(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    k = key()
    await client.post(f"/_idem/{app_id}", content=b'{"revision":1,"term_months":24}', headers=_h(k))
    again = await client.post(
        f"/_idem/{app_id}", content=b'{"term_months": 24, "revision": 1}', headers=_h(k)
    )
    assert again.status_code == 201
    assert await revision(db) == 2


def _h(k: str) -> dict[str, str]:
    return {"Idempotency-Key": k, "Content-Type": "application/json"}


async def test_same_key_other_body_or_path_is_reused_error(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    k = key()
    await call(client, app_id, k, revision=1, term_months=24)
    other_body = await call(client, app_id, k, revision=1, term_months=36)
    other_path = await call(client, str(uuid.uuid4()), k, revision=1, term_months=24)
    for response in (other_body, other_path):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert await revision(db) == 2


async def test_parallel_same_key_gives_one_effect(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    k = key()
    responses = await asyncio.gather(
        call(client, app_id, k, revision=1, term_months=24, mode="slow"),
        call(client, app_id, k, revision=1, term_months=24, mode="slow"),
    )
    outcomes = sorted((r.status_code, r.json().get("error", {}).get("code")) for r in responses)
    assert outcomes in (
        [(201, None), (409, "IDEMPOTENCY_IN_PROGRESS")],
        [(201, None), (201, None)],  # второй пришёл после COMMIT первого — сохранённый ответ
    )
    assert await revision(db) == 2
    assert await keys(db) == [("COMPLETED", 201)]


async def test_parallel_different_keys_conflict_on_revision(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    responses = await asyncio.gather(
        *(call(client, app_id, key(), revision=1, term_months=t, mode="slow") for t in (24, 36))
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "REVISION_CONFLICT"
    }
    assert await revision(db) == 2
    assert await keys(db) == [("COMPLETED", 201)]  # ключ проигравшего удалён


async def test_error_is_not_cached_and_key_is_freed(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    k = key()
    stale = await call(client, app_id, k, revision=7, term_months=24)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVISION_CONFLICT"
    assert await keys(db) == []
    retry = await call(client, app_id, k, revision=1, term_months=24)  # тот же ключ, новое тело
    assert retry.status_code == 201


async def test_validation_error_frees_key(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    response = await call(client, app_id, key(), revision="x", term_months=24)
    assert response.status_code == 422
    assert await keys(db) == []


async def test_failure_after_complete_rolls_back_effect_and_key(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    # ASGITransport пробрасывает необработанное исключение после ответа 500 (как uvicorn в лог)
    with pytest.raises(RuntimeError, match="сбой после complete"):
        await call(client, app_id, key(), revision=1, term_months=24, mode="fail_after_complete")
    assert await revision(db) == 1
    assert await keys(db) == []


async def test_route_without_complete_does_not_keep_key(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    response = await call(client, app_id, key(), revision=1, term_months=24, mode="skip_complete")
    assert response.status_code == 201
    assert await keys(db) == []


async def test_stolen_record_rolls_back_effect(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    response = await call(client, app_id, key(), revision=1, term_months=24, mode="steal")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
    assert await revision(db) == 1


async def _put_key(
    db: AsyncEngine, app_id: str, k: str, status_: str, age: timedelta, body: dict[str, Any]
) -> None:
    path = f"/api/v1/_idem/{app_id}"
    async with db.begin() as conn:
        user_id = await conn.scalar(sa.text("SELECT id FROM users WHERE email = :e"), {"e": BAKERY})
        await conn.execute(
            sa.text(
                "INSERT INTO idempotency_keys (user_id, key, status, method, canonical_path, "
                "request_hash, status_code, response_json, created_at) VALUES (:u, :k, :s, 'POST', "
                ":p, :h, :code, CAST(:resp AS jsonb), now() - CAST(:age AS interval))"
            ),
            {
                "u": user_id,
                "k": k,
                "s": status_,
                "p": path,
                "h": request_hash("POST", path, body),
                "code": 201 if status_ == "COMPLETED" else None,
                "resp": '{"stale": true}' if status_ == "COMPLETED" else None,
                "age": f"{int(age.total_seconds())} seconds",
            },
        )


async def test_fresh_in_progress_blocks_and_abandoned_is_taken_over(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    body = {"revision": 1, "term_months": 24, "mode": "ok"}
    fresh, old = key(), key()
    await _put_key(db, app_id, fresh, "IN_PROGRESS", timedelta(seconds=10), body)
    await _put_key(db, app_id, old, "IN_PROGRESS", timedelta(seconds=61), body)
    blocked = await call(client, app_id, fresh, **body)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
    taken = await call(client, app_id, old, **body)
    assert taken.status_code == 201
    assert await revision(db) == 2


async def test_completed_older_than_day_expires(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    body = {"revision": 1, "term_months": 24, "mode": "ok"}
    recent, expired = key(), key()
    await _put_key(db, app_id, recent, "COMPLETED", timedelta(hours=23), body)
    await _put_key(db, app_id, expired, "COMPLETED", timedelta(hours=25), body)
    replay = await call(client, app_id, recent, **body)
    assert replay.json() == {"stale": True}  # сохранённый ответ, без выполнения
    assert await revision(db) == 1
    fresh = await call(client, app_id, expired, **body)
    assert fresh.json() == {"revision": 2, "term_months": 24}


async def test_missing_key_is_validation_error(client: httpx.AsyncClient, app_id: str) -> None:
    response = await call(client, app_id, None, revision=1, term_months=24)
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert fields[0]["field"] == "header.Idempotency-Key"


async def test_canonical_path_has_prefix_and_lowercase_uuid(
    client: httpx.AsyncClient, app_id: str, db: AsyncEngine
) -> None:
    await call(client, app_id.upper(), key(), revision=1, term_months=24)
    async with db.connect() as conn:
        path = await conn.scalar(sa.text("SELECT canonical_path FROM idempotency_keys"))
    assert path == f"/api/v1/_idem/{app_id}"


async def test_keys_are_scoped_per_user(
    client: httpx.AsyncClient,
    app_id: str,
    db: AsyncEngine,
    as_user: AsUser,
    bind_company: BindCompany,
) -> None:
    k = key()
    assert (await call(client, app_id, k, revision=1, term_months=24)).status_code == 201
    await bind_company(TECHSERVICE, TECHSERVICE_INN)
    other = await as_user(TECHSERVICE)
    own = (await client.post("/applications", json={}, headers=other)).json()["id"]
    response = await client.post(
        f"/_idem/{own}", json={"revision": 1, "term_months": 12}, headers={**other, **_h(k)}
    )
    assert response.status_code == 201  # тот же ключ у другого клиента — не повтор и не 422
    assert await count(db, "idempotency_keys") == 2


def test_request_hash_depends_on_method_path_and_body() -> None:
    base = request_hash("POST", "/a", {"x": 1})
    assert base == request_hash("post", "/a", {"x": 1})
    assert base != request_hash("PUT", "/a", {"x": 1})
    assert base != request_hash("POST", "/b", {"x": 1})
    assert base != request_hash("POST", "/a", {"x": 2})


def test_app_error_codes_exist() -> None:
    assert AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "").status_code == 409
    assert AppError(ErrorCode.IDEMPOTENCY_KEY_REUSED, "").status_code == 422
