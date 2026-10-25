"""Idempotency-Key (#5) на тестовом роутере: изменяющих эндпоинтов до #7 нет.

Эффект — строка в отдельной таблице `idem_test_effects`, записанная в одной транзакции
с `idem.complete()`, как будут делать эндпоинты #7.
"""

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUserDep
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.idempotency import (
    Idempotency,
    IdempotencyKeyHeader,
    canonical_json,
    idempotent,
    request_hash,
)
from app.main import create_app
from app.schemas.common import ErrorCode
from tests.conftest import CLIENT_LOGIN, MANAGER_LOGIN, TEST_DATABASE_URL, bearer, demo_user_id

Serve = Callable[[Any], Awaitable[httpx.AsyncClient]]
ITEM = "7f3e2a10-0000-4000-8000-000000000001"
URL = f"/api/v1/_idem/items/{ITEM}/act"
KEY = {"Idempotency-Key": "key-00000001"}


class Body(BaseModel):
    revision: int
    note: str = ""


@dataclass
class Behaviour:
    """Чем закончится следующий вызов эндпоинта; меняется тестом между запросами."""

    calls: int = 0
    fail_before_effect: AppError | None = None
    raise_after_commit: bool = False
    raise_before_commit: bool = False
    gate: asyncio.Event | None = None
    commit_gate: asyncio.Event | None = None
    at_commit: asyncio.Event = field(default_factory=asyncio.Event)
    entered: asyncio.Event = field(default_factory=asyncio.Event)


def make_router(behaviour: Behaviour) -> APIRouter:
    router = APIRouter()

    @router.post("/_idem/items/{item_id}/act", status_code=201)
    async def act(
        item_id: uuid.UUID,
        body: Body,
        user: CurrentUserDep,
        session: Annotated[AsyncSession, Depends(get_db)],
        idem: Annotated[Idempotency, Depends(idempotent)],
        idempotency_key: IdempotencyKeyHeader,
    ) -> dict[str, Any]:
        behaviour.calls += 1
        behaviour.entered.set()
        if behaviour.gate is not None:
            await behaviour.gate.wait()
        if behaviour.fail_before_effect is not None:
            raise behaviour.fail_before_effect
        await session.begin()
        effect = await session.scalar(
            sa.text("INSERT INTO idem_test_effects (user_id, note) VALUES (:u, :n) RETURNING id"),
            {"u": user.id, "n": body.note},
        )
        payload = {"effect_id": effect, "item_id": str(item_id), "revision": body.revision + 1}
        stored = await idem.complete(session, 201, payload)
        if behaviour.commit_gate is not None:
            behaviour.at_commit.set()
            await behaviour.commit_gate.wait()
        if behaviour.raise_before_commit:
            raise RuntimeError("сбой до COMMIT")
        await session.commit()
        if behaviour.raise_after_commit:
            raise RuntimeError("ответ потерян после COMMIT")
        return stored

    return router


def sql(statement: str, **params: Any) -> Any:
    engine = sa.create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        result = conn.execute(sa.text(statement), params)
        rows = result.all() if result.returns_rows else None
    engine.dispose()
    return rows


def effects() -> int:
    rows = sql("SELECT count(*) FROM idem_test_effects")
    return int(rows[0][0])


def keys() -> list[tuple[str, str, int | None]]:
    return [tuple(r) for r in sql("SELECT key, status, status_code FROM idempotency_keys")]


@pytest.fixture
def effects_table(db_reset: None) -> Iterator[None]:
    sql(
        "CREATE TABLE IF NOT EXISTS idem_test_effects "
        "(id serial PRIMARY KEY, user_id uuid NOT NULL, note text NOT NULL)"
    )
    sql("TRUNCATE idem_test_effects")
    yield
    sql("DROP TABLE idem_test_effects")


@pytest.fixture
def behaviour() -> Behaviour:
    return Behaviour()


@pytest.fixture
async def api(
    make_settings: Callable[..., Settings],
    effects_table: None,
    behaviour: Behaviour,
    serve: Serve,
) -> httpx.AsyncClient:
    app: FastAPI = create_app(make_settings())
    app.include_router(make_router(behaviour), prefix="/api/v1")
    return await serve(app)


def act(
    api: httpx.AsyncClient,
    body: dict[str, Any] | None = None,
    *,
    url: str = URL,
    login: str = CLIENT_LOGIN,
    key: dict[str, str] = KEY,
) -> Awaitable[httpx.Response]:
    return api.post(url, json=body or {"revision": 1}, headers={**bearer(login), **key})


# --- Протокол --------------------------------------------------------------------------


async def test_replay_returns_saved_response_without_calling_endpoint(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    first = await act(api)
    assert first.status_code == 201, first.text
    second = await act(api)
    assert second.status_code == 201
    assert second.json() == first.json()
    assert behaviour.calls == 1
    assert effects() == 1
    assert keys() == [("key-00000001", "COMPLETED", 201)]


async def test_body_order_and_whitespace_do_not_change_hash(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    await act(api, {"revision": 1, "note": "a"})
    raw = b'{ "note" : "a",\n "revision": 1 }'
    response = await api.post(
        URL,
        content=raw,
        headers={**bearer(CLIENT_LOGIN), **KEY, "Content-Type": "application/json"},
    )
    assert response.status_code == 201
    assert behaviour.calls == 1


async def test_uuid_case_in_path_is_canonical(api: httpx.AsyncClient, behaviour: Behaviour) -> None:
    await act(api)
    assert (await act(api, url=URL.replace(ITEM, ITEM.upper()))).status_code == 201
    assert behaviour.calls == 1


@pytest.mark.parametrize(
    ("body", "url"),
    [
        ({"revision": 2}, URL),
        ({"revision": 1, "note": "x"}, URL),
        ({"revision": 1}, URL.replace(ITEM, str(uuid.UUID(int=7)))),
    ],
    ids=["other-body", "extra-field", "other-path"],
)
async def test_same_key_other_request_is_422(
    api: httpx.AsyncClient, behaviour: Behaviour, body: dict[str, Any], url: str
) -> None:
    await act(api)
    response = await act(api, body, url=url)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert behaviour.calls == 1


async def test_keys_are_scoped_per_user(api: httpx.AsyncClient, behaviour: Behaviour) -> None:
    assert (await act(api)).status_code == 201
    assert (await act(api, login="director.bakery@creditflow.demo")).status_code == 201
    assert behaviour.calls == 2
    assert effects() == 2


async def test_missing_key_is_validation_error(api: httpx.AsyncClient) -> None:
    response = await api.post(URL, json={"revision": 1}, headers=bearer(CLIENT_LOGIN))
    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert fields[0]["field"] == "header.Idempotency-Key"


async def test_without_token_is_401_before_key_check(api: httpx.AsyncClient) -> None:
    response = await api.post(URL, json={"revision": 1}, headers=KEY)
    assert response.status_code == 401
    assert keys() == []


async def test_concurrent_requests_with_one_key(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    behaviour.gate = asyncio.Event()
    first = asyncio.ensure_future(act(api))
    await asyncio.wait_for(behaviour.entered.wait(), 5)
    second = await act(api)  # первый ещё в эндпоинте
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"
    behaviour.gate.set()
    assert (await first).status_code == 201
    assert behaviour.calls == 1
    assert effects() == 1


async def test_parallel_burst_with_one_key_has_one_effect(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    responses = await asyncio.gather(*(act(api) for _ in range(8)))
    statuses = sorted(r.status_code for r in responses)
    assert statuses.count(201) >= 1
    assert set(statuses) <= {201, 409}
    assert behaviour.calls == 1
    assert effects() == 1


async def test_503_is_not_cached_and_retry_runs_again(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    behaviour.fail_before_effect = AppError(ErrorCode.PROVIDER_UNAVAILABLE, "ext-sim недоступен")
    failed = await act(api)
    assert failed.status_code == 503
    assert keys() == []  # запись снята до отправки ответа
    behaviour.fail_before_effect = None
    retry = await act(api)
    assert retry.status_code == 201
    assert behaviour.calls == 2
    assert effects() == 1


@pytest.mark.parametrize(
    "error",
    [ErrorCode.REVISION_CONFLICT, ErrorCode.CONSENT_REQUIRED, ErrorCode.INTERNAL_ERROR],
)
async def test_errors_are_not_cached(
    api: httpx.AsyncClient, behaviour: Behaviour, error: ErrorCode
) -> None:
    behaviour.fail_before_effect = AppError(error, "ошибка")
    assert (await act(api)).status_code >= 400
    behaviour.fail_before_effect = None
    assert (await act(api)).status_code == 201
    assert behaviour.calls == 2


async def test_unhandled_exception_is_not_cached(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    behaviour.raise_before_commit = True
    response = await act(api)  # complete() вызван, но COMMIT не случился
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert keys() == []
    assert effects() == 0
    behaviour.raise_before_commit = False
    assert (await act(api)).status_code == 201
    assert effects() == 1


async def test_lost_response_after_commit_replays_instead_of_duplicating(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    behaviour.raise_after_commit = True
    lost = await act(api)
    assert lost.status_code == 500  # клиент ответа не увидел
    assert keys() == [("key-00000001", "COMPLETED", 201)]  # очистка не тронула COMPLETED
    behaviour.raise_after_commit = False
    retry = await act(api)
    assert retry.status_code == 201
    assert retry.json()["revision"] == 2
    assert behaviour.calls == 1
    assert effects() == 1


# --- Брошенные записи и TTL -------------------------------------------------------------


def _seed_key(status: str, age_seconds: int, body: dict[str, Any] | None = None) -> None:
    path = URL.rstrip("/")
    digest = request_hash("POST", path, json.dumps(body or {"revision": 1}).encode())
    sql(
        "INSERT INTO idempotency_keys (user_id, key, status, method, canonical_path, "
        "request_hash, status_code, response_json, created_at) VALUES (:u, :k, :s, 'POST', "
        ":p, :h, :code, CAST(:resp AS jsonb), clock_timestamp() - make_interval(secs => :age))",
        u=demo_user_id(CLIENT_LOGIN),
        k=KEY["Idempotency-Key"],
        s=status,
        p=path,
        h=digest,
        code=201 if status == "COMPLETED" else None,
        resp='{"old": true}' if status == "COMPLETED" else None,
        age=age_seconds,
    )


async def test_fresh_in_progress_is_409(api: httpx.AsyncClient, behaviour: Behaviour) -> None:
    _seed_key("IN_PROGRESS", 5)
    response = await act(api)
    assert response.status_code == 409
    assert behaviour.calls == 0
    assert keys() == [("key-00000001", "IN_PROGRESS", None)]  # чужую запись не трогаем


async def test_stale_in_progress_is_taken_over(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    _seed_key("IN_PROGRESS", 61)
    response = await act(api)
    assert response.status_code == 201
    assert behaviour.calls == 1
    assert keys() == [("key-00000001", "COMPLETED", 201)]


async def test_stale_in_progress_with_other_body_is_still_422(api: httpx.AsyncClient) -> None:
    _seed_key("IN_PROGRESS", 61, {"revision": 9})
    response = await act(api)
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


async def test_completed_older_than_ttl_is_reexecuted(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    _seed_key("COMPLETED", 24 * 3600 + 1)
    response = await act(api)
    assert response.status_code == 201
    assert response.json() != {"old": True}
    assert behaviour.calls == 1


async def test_completed_within_ttl_is_replayed(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    _seed_key("COMPLETED", 23 * 3600)
    response = await act(api)
    assert response.status_code == 201
    assert response.json() == {"old": True}
    assert behaviour.calls == 0


async def test_taken_over_request_cannot_commit_its_effect(
    api: httpx.AsyncClient, behaviour: Behaviour
) -> None:
    """Fencing: запрос A завис дольше 60 с, запрос B перехватил ключ и завершился.
    complete() у A не находит своей записи, и эффект A откатывается."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    _seed_key("IN_PROGRESS", 61)
    token: datetime = sql(
        "SELECT created_at FROM idempotency_keys WHERE key = :k", k=KEY["Idempotency-Key"]
    )[0][0]
    stale = Idempotency(user_id=demo_user_id(CLIENT_LOGIN), key=KEY["Idempotency-Key"], token=token)

    assert (await act(api)).status_code == 201  # B перехватил и закоммитил
    factory: async_sessionmaker[AsyncSession] = api._transport.app.state.session_factory  # type: ignore[attr-defined]
    async with factory() as session:
        await session.begin()
        await session.execute(
            sa.text("INSERT INTO idem_test_effects (user_id, note) VALUES (:u, 'A')"),
            {"u": demo_user_id(CLIENT_LOGIN)},
        )
        with pytest.raises(AppError) as exc:
            await stale.complete(session, 201, {"from": "A"})
        assert exc.value.code is ErrorCode.IDEMPOTENCY_IN_PROGRESS
        await session.rollback()
    assert effects() == 1
    assert keys() == [("key-00000001", "COMPLETED", 201)]


async def test_complete_rejects_non_2xx(api: httpx.AsyncClient) -> None:
    stale = Idempotency(
        user_id=demo_user_id(MANAGER_LOGIN), key="k", token=datetime.now().astimezone()
    )
    with pytest.raises(ValueError, match="2xx"):
        await stale.complete(None, 409, {})  # type: ignore[arg-type]


# --- Каноническая форма ----------------------------------------------------------------


def test_canonical_json() -> None:
    assert canonical_json(b"") == canonical_json(b"  ") == ""
    assert canonical_json(b'{"b":1,"a":[1,2]}') == canonical_json(b'{ "a": [1, 2], "b": 1 }')
    assert canonical_json('{"a":"ё"}'.encode()) == '{"a":"ё"}'
    assert canonical_json(b"not json").startswith("raw:")


def test_hash_binds_method_path_and_body() -> None:
    base = request_hash("POST", "/a", b'{"x":1}')
    assert base == request_hash("post", "/a", b'{ "x" : 1 }')
    assert base != request_hash("PATCH", "/a", b'{"x":1}')
    assert base != request_hash("POST", "/b", b'{"x":1}')
    assert base != request_hash("POST", "/a", b'{"x":2}')


def test_openapi_has_single_idempotency_header(make_settings: Callable[..., Settings]) -> None:
    app = create_app(make_settings())
    app.include_router(make_router(Behaviour()), prefix="/api/v1")
    params = app.openapi()["paths"]["/api/v1/_idem/items/{item_id}/act"]["post"]["parameters"]
    assert [p["name"] for p in params if p["in"] == "header"] == ["Idempotency-Key"]


async def test_takeover_waits_for_completed_but_uncommitted_request(
    api: httpx.AsyncClient, behaviour: Behaviour, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A выполнил complete(), но ещё не закоммитил, а запись уже «устарела». Перехват B
    ждёт блокировку строки и после COMMIT A получает сохранённый ответ, а не второй
    эффект."""
    import app.core.idempotency as idempotency

    monkeypatch.setattr(idempotency, "STALE_AFTER", timedelta(0))
    commit_a = behaviour.commit_gate = asyncio.Event()
    first = asyncio.ensure_future(act(api))
    await asyncio.wait_for(behaviour.at_commit.wait(), 5)
    behaviour.commit_gate = None
    second = asyncio.ensure_future(act(api))
    await asyncio.sleep(0.3)
    assert not second.done()  # UPDATE перехвата ждёт блокировку строки у A
    commit_a.set()
    a, b = await asyncio.wait_for(asyncio.gather(first, second), 5)
    assert (a.status_code, b.status_code) == (201, 201)
    assert a.json() == b.json()
    assert behaviour.calls == 1
    assert effects() == 1
    assert keys() == [("key-00000001", "COMPLETED", 201)]
