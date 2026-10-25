"""IdempotencyService: `Idempotency-Key` для изменяющих запросов (design.md §3.7, issue #7).

Подключение в маршруте: параметр `idem: Idem`, а внутри транзакции бизнес-эффекта —
`await idem.complete(session, status_code, body)` до COMMIT.

1. Отпечаток: `sha256(method + canonical_path + canonical_json(body))`; `canonical_path` —
   шаблон маршрута с подставленными path-параметрами, без query и завершающего `/`.
2. Вход (отдельная короткая транзакция): запись `IN_PROGRESS` по `(user_id, key)`. Если
   запись уже есть: тот же запрос и `IN_PROGRESS` → 409 `IDEMPOTENCY_IN_PROGRESS`; тот же
   и `COMPLETED` → сохранённый ответ без повторного выполнения; другой метод, путь или
   тело → 422 `IDEMPOTENCY_KEY_REUSED`.
3. Успех: `complete` пишет `COMPLETED` с ответом в транзакции бизнес-эффекта — либо оба,
   либо ничего.
4. Ошибка: при исключении (4xx, 5xx, сбой) запись удаляется до отправки ответа,
   поэтому повтор выполняется заново. Ответы-ошибки не кешируются.
5. `IN_PROGRESS` старше 60 с — брошенная (процесс упал): её перехватывает новый запрос.
   `COMPLETED` старше 24 ч — истёкшая, ключ можно использовать заново.

`created_at` записи служит меткой владельца: `complete` и удаление действуют, только если
запись всё ещё наша. Если брошенную запись перехватили, `complete` откатит эффект (409).
"""

import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import sessionmaker_of
from app.core.errors import AppError
from app.core.security import CurrentUser, current_user
from app.db.models import IdempotencyKey
from app.schemas.common import ErrorCode

logger = logging.getLogger("app.idempotency")

ABANDONED_AFTER = timedelta(seconds=60)
EXPIRES_AFTER = timedelta(hours=24)

IN_PROGRESS = "IN_PROGRESS"
COMPLETED = "COMPLETED"


class IdempotentReplay(Exception):
    """Сохранённый ответ: перехватывается обработчиком и отдаётся без вызова маршрута."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(status_code)
        self.status_code, self.body = status_code, body


def install_idempotency_handlers(app: FastAPI) -> None:
    @app.exception_handler(IdempotentReplay)
    async def _replay(_: Request, exc: IdempotentReplay) -> JSONResponse:
        return JSONResponse(exc.body, status_code=exc.status_code)


def _normalized(value: str) -> str:
    try:
        return str(uuid.UUID(value))  # регистр и форма записи UUID не меняют отпечаток
    except ValueError:
        return value


def canonical_path(request: Request) -> str:
    """`/api/v1/applications/<uuid>/submit`: шаблон маршрута с нормализованными параметрами.

    `scope["route"].path_format` у подключённого роутера — без его префикса, поэтому
    префикс берётся из фактического пути запроса.
    """
    path = request.url.path.rstrip("/") or "/"
    path_format: str | None = getattr(request.scope.get("route"), "path_format", None)
    if path_format is None:
        return path
    raw = path_format.format(**request.path_params).rstrip("/")
    if not path.endswith(raw):
        return path
    params = {k: _normalized(str(v)) for k, v in request.path_params.items()}
    return path[: len(path) - len(raw)] + path_format.format(**params).rstrip("/")


def request_hash(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{method.upper()} {path}\n{canonical}".encode()).hexdigest()


@dataclass
class Idempotency:
    user_id: uuid.UUID
    key: str
    owner_mark: datetime  # created_at нашей записи
    completed: bool = field(default=False)

    async def complete(self, session: AsyncSession, status_code: int, body: Any) -> None:
        """Внутри транзакции бизнес-эффекта, до COMMIT. `body` — JSON-совместимый ответ."""
        result = await session.execute(
            update(IdempotencyKey)
            .where(
                IdempotencyKey.user_id == self.user_id,
                IdempotencyKey.key == self.key,
                IdempotencyKey.status == IN_PROGRESS,
                IdempotencyKey.created_at == self.owner_mark,
            )
            .values(status=COMPLETED, status_code=status_code, response_json=body)
        )
        if result.rowcount != 1:  # type: ignore[attr-defined]
            # запись перехвачена как брошенная: эффект этой попытки откатывается
            raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "Запрос уже обрабатывается")
        self.completed = True


async def _acquire(
    sessions: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    key: str,
    method: str,
    path: str,
    fingerprint: str,
) -> datetime:
    """Короткая транзакция: создать или перехватить запись. Возвращает метку владельца."""
    async with sessions() as session, session.begin():
        mark = await session.scalar(
            insert(IdempotencyKey)
            .values(
                user_id=user_id,
                key=key,
                status=IN_PROGRESS,
                method=method,
                canonical_path=path,
                request_hash=fingerprint,
                created_at=func.clock_timestamp(),
            )
            .on_conflict_do_nothing(index_elements=["user_id", "key"])
            .returning(IdempotencyKey.created_at)
        )
        if mark is not None:
            return mark

        existing = await session.scalar(
            select(IdempotencyKey)
            .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
            .with_for_update()
        )
        assert existing is not None  # конфликт по PK = запись есть; удаляет её только владелец
        now = await session.scalar(select(func.clock_timestamp()))
        assert now is not None
        age = now - existing.created_at
        expired = existing.status == COMPLETED and age > EXPIRES_AFTER
        abandoned = existing.status == IN_PROGRESS and age > ABANDONED_AFTER
        if not expired:
            same = (existing.method, existing.canonical_path, existing.request_hash) == (
                method,
                path,
                fingerprint,
            )
            if not same:
                raise AppError(
                    ErrorCode.IDEMPOTENCY_KEY_REUSED,
                    "Ключ уже использован для другого запроса",
                )
            if existing.status == COMPLETED:
                assert existing.status_code is not None
                raise IdempotentReplay(existing.status_code, existing.response_json)
            if not abandoned:
                raise AppError(ErrorCode.IDEMPOTENCY_IN_PROGRESS, "Запрос уже обрабатывается")
            logger.warning("idempotency: перехват брошенной записи (возраст %s)", age)
        existing.status = IN_PROGRESS
        existing.method, existing.canonical_path = method, path
        existing.request_hash = fingerprint
        existing.status_code = existing.response_json = None
        existing.created_at = now
        return now


async def _release(sessions: async_sessionmaker[AsyncSession], idem: Idempotency) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.user_id == idem.user_id,
                IdempotencyKey.key == idem.key,
                IdempotencyKey.status == IN_PROGRESS,
                IdempotencyKey.created_at == idem.owner_mark,
            )
        )


async def idempotency(
    request: Request,
    user: Annotated[CurrentUser, Depends(current_user)],
    key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=128, description="UUID запроса"),
    ],
) -> AsyncIterator[Idempotency]:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = {"__raw__": raw.decode(errors="replace")}  # невалидный JSON отклонит валидация
    path = canonical_path(request)
    sessions = sessionmaker_of(request)
    mark = await _acquire(
        sessions, user.id, key, request.method, path, request_hash(request.method, path, body)
    )
    idem = Idempotency(user.id, key, mark)
    try:
        yield idem
    except Exception:
        await _release(sessions, idem)
        raise
    if not idem.completed:
        # маршрут вернул успех, не вызвав complete: эффект не защищён — это ошибка кода
        logger.error("idempotency: %s %s завершился без complete()", request.method, path)
        await _release(sessions, idem)


# scope="function": удаление ключа после ошибки — до отправки ответа клиенту,
# иначе немедленный повтор успел бы получить 409 IDEMPOTENCY_IN_PROGRESS.
Idem = Annotated[Idempotency, Depends(idempotency, scope="function")]
