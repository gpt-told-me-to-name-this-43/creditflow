"""`Idempotency-Key` для изменяющих запросов (#5).

Протокол для эндпоинтов (#7: submit, decisions, offer/accept, offer/decline, info-response,
sign):

1. Эндпоинт объявляет `idem: Idempotency = Depends(idempotent)`. Зависимость читает
   заголовок `Idempotency-Key`, считает
   `request_hash = sha256(method + canonical_path + canonical_json(body))` и отдельной
   короткой транзакцией вставляет запись `IN_PROGRESS`
   (`INSERT … ON CONFLICT (user_id, key) DO NOTHING`). Ключ принадлежит пользователю:
   PK `(user_id, key)`, одинаковые ключи разных пользователей не пересекаются.
2. Запись уже есть:
   - другой метод, путь или тело — `422 IDEMPOTENCY_KEY_REUSED`;
   - тот же запрос, `COMPLETED` — сохранённые `status_code` и JSON возвращаются
     исключением `IdempotentReplay` до вызова эндпоинта: обработчик не выполняется;
   - тот же запрос, `IN_PROGRESS` моложе 60 с — `409 IDEMPOTENCY_IN_PROGRESS`;
   - тот же запрос, `IN_PROGRESS` старше 60 с — запись перехватывается (см. ниже);
   - запись старше 24 ч (TTL) — считается отсутствующей и перезаписывается.
3. Бизнес-код вызывает `await idem.complete(session, status_code, payload)` внутри своей
   транзакции, до `COMMIT`: ответ сохраняется атомарно с эффектом. Повтор после потери
   HTTP-ответа получает этот ответ, а не второй эффект. `complete()` возвращает
   сохранённый JSON; эндпоинт отдаёт тот же объект, что передал в `complete()`.
4. Эндпоинт завершился не-2xx, исключением или без `complete()` — зависимость откатывает
   незакоммиченную транзакцию сессии, переданной в `complete()`, и удаляет свою запись
   `IN_PROGRESS`, чтобы повтор выполнился заново. Запись `COMPLETED` не удаляется
   никогда: если исключение случилось после `COMMIT`, повтор получит сохранённый ответ.

Перехват устаревшей записи. Время захвата `created_at` служит fencing-токеном.
Перехват — условный `UPDATE … WHERE status = 'IN_PROGRESS' AND created_at = <старый>`,
он выставляет новый `created_at`. `complete()` — `UPDATE … WHERE status = 'IN_PROGRESS'
AND created_at = <свой токен>`; если строка не обновлена (запрос перехватили или он уже
завершён), `complete()` бросает `409 IDEMPOTENCY_IN_PROGRESS`, и транзакция эффекта
откатывается. Обе операции блокируют одну строку, поэтому закоммитить эффект с отметкой
`COMPLETED` может только один запрос. Ограничение: гарантия покрывает только эффекты
в той же транзакции, что и `complete()`. Действия вне неё (вызовы ext-sim, отдельные
транзакции вроде согласия БКИ в submit) обязаны быть идемпотентными сами.
"""

import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.routing import Route

from app.auth.deps import CurrentUserDep
from app.core.errors import AppError
from app.db.models import IdempotencyKey as Row
from app.schemas.common import ErrorCode

IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"
STALE_AFTER = timedelta(seconds=60)
KEY_TTL = timedelta(hours=24)
_CLAIM_ATTEMPTS = 3

IdempotencyKeyHeader = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=128, description="UUID запроса")
]


class IdempotentReplay(Exception):
    def __init__(self, status_code: int, payload: Any) -> None:
        super().__init__(status_code)
        self.status_code, self.payload = status_code, payload


def install_idempotency(app: FastAPI) -> None:
    @app.exception_handler(IdempotentReplay)
    async def _replay(_: Request, exc: IdempotentReplay) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.payload)


def canonical_path(request: Request) -> str:
    """Шаблон маршрута с подставленными параметрами, без query и завершающего `/`."""
    path: str = request.scope["path"]
    route = request.scope.get("route")
    if isinstance(route, Route):
        # path_format маршрута из include_router не содержит префикс роутера (FastAPI
        # 0.159): префикс берём из фактического пути, шаблон — с каноническими параметрами.
        raw = route.path_format.format(**request.path_params)
        if path.endswith(raw):
            params = {name: _canonical_param(v) for name, v in request.path_params.items()}
            path = path[: len(path) - len(raw)] + route.path_format.format(**params)
    return path.rstrip("/") or "/"


def _canonical_param(value: object) -> str:
    try:
        return str(UUID(str(value)))  # регистр и форма записи UUID не меняют путь
    except ValueError:
        return str(value)


def canonical_json(body: bytes) -> str:
    if not body.strip():
        return ""
    try:
        data = json.loads(body)
    except ValueError:
        return "raw:" + hashlib.sha256(body).hexdigest()
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(method: str, path: str, body: bytes) -> str:
    return hashlib.sha256((method.upper() + path + canonical_json(body)).encode()).hexdigest()


@dataclass
class Idempotency:
    user_id: uuid.UUID
    key: str
    token: datetime
    _business_session: AsyncSession | None = field(default=None, repr=False)

    def _own(self) -> Any:
        return (
            (Row.user_id == self.user_id)
            & (Row.key == self.key)
            & (Row.status == IN_PROGRESS)
            & (Row.created_at == self.token)
        )

    async def complete(self, session: AsyncSession, status_code: int, payload: Any) -> Any:
        if not 200 <= status_code < 300:
            raise ValueError("сохраняются только 2xx")
        content = jsonable_encoder(payload)
        self._business_session = session
        result = await session.execute(
            update(Row)
            .where(self._own())
            .values(status=COMPLETED, status_code=status_code, response_json=content)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            # Запись перехвачена другим запросом после 60 с или уже завершена: эффект
            # этого запроса не должен закоммититься.
            raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "Запрос уже обрабатывается")
        return content

    async def _release(self, factory: async_sessionmaker[AsyncSession]) -> None:
        business = self._business_session
        if business is not None and business.in_transaction():
            # Незакоммиченная транзакция с complete() держит блокировку строки:
            # без отката DELETE ниже ждал бы её до закрытия сессии.
            await business.rollback()
        async with factory() as session, session.begin():
            await session.execute(delete(Row).where(self._own()))


async def _claim(
    factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    key: str,
    method: str,
    path: str,
    digest: str,
) -> datetime:
    now = func.clock_timestamp()
    fresh = {
        "status": IN_PROGRESS,
        "method": method,
        "canonical_path": path,
        "request_hash": digest,
        "status_code": None,
        "response_json": None,
    }
    for _ in range(_CLAIM_ATTEMPTS):
        async with factory() as session, session.begin():
            token = await session.scalar(
                insert(Row)
                .values(user_id=user_id, key=key, created_at=now, **fresh)
                .on_conflict_do_nothing(index_elements=["user_id", "key"])
                .returning(Row.created_at)
            )
            if token is not None:
                return token
            existing = (
                await session.execute(
                    select(Row, (now - Row.created_at).label("age")).where(
                        Row.user_id == user_id, Row.key == key
                    )
                )
            ).one_or_none()
            if existing is None:
                continue  # запись удалили между INSERT и SELECT — пробуем снова
            row, age = existing
            if age > KEY_TTL:
                condition = Row.created_at == row.created_at
            elif row.request_hash != digest:
                raise AppError(
                    ErrorCode.IDEMPOTENCY_KEY_REUSED, "Ключ использован с другим запросом"
                )
            elif row.status == COMPLETED:
                raise IdempotentReplay(row.status_code, row.response_json)
            elif age <= STALE_AFTER:
                raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "Запрос уже обрабатывается")
            else:
                condition = (Row.created_at == row.created_at) & (Row.status == IN_PROGRESS)
            token = await session.scalar(
                update(Row)
                .where(Row.user_id == user_id, Row.key == key, condition)
                .values(created_at=now, **fresh)
                .returning(Row.created_at)
            )
            if token is not None:
                return token
    raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "Запрос уже обрабатывается")


async def _idempotency_scope(
    request: Request, user: CurrentUserDep, key: IdempotencyKeyHeader
) -> AsyncIterator[Idempotency]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    path = canonical_path(request)
    digest = request_hash(request.method, path, await request.body())
    token = await _claim(factory, user.id, key, request.method.upper(), path, digest)
    idem = Idempotency(user_id=user.id, key=key, token=token)
    try:
        yield idem
    finally:
        await idem._release(factory)


async def idempotent(
    idem: Annotated[Idempotency, Depends(_idempotency_scope, scope="function")],
) -> Idempotency:
    """Зависимость эндпоинта. scope="function": запись снимается до отправки ответа,
    поэтому немедленный повтор после ошибки не получает 409."""
    return idem
