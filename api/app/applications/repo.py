"""Загрузка заявки клиента: чтение и блокировка под изменение (design.md §3.7, §4).

Чужая или несуществующая заявка — 404, без раскрытия, что она существует.
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Application
from app.schemas.common import ErrorCode, RevisionConflictDetails


def _owned(application_id: uuid.UUID, owner_id: uuid.UUID) -> Select[Application]:
    return select(Application).where(
        Application.id == application_id, Application.owner_user_id == owner_id
    )


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Заявка не найдена")


async def get_owned(
    session: AsyncSession, application_id: uuid.UUID, owner_id: uuid.UUID
) -> Application:
    application = await session.scalar(_owned(application_id, owner_id))
    if application is None:
        raise _not_found()
    return application


async def lock_owned(
    session: AsyncSession, application_id: uuid.UUID, owner_id: uuid.UUID
) -> Application:
    """`SELECT … FOR UPDATE` внутри уже открытой транзакции. Конкурент ждёт COMMIT
    и затем видит новую `revision`, поэтому проверка `ensure_revision` после блокировки
    отсекает второй запрос по устаревшим данным."""
    application = await session.scalar(
        _owned(application_id, owner_id).with_for_update().execution_options(populate_existing=True)
    )
    if application is None:
        raise _not_found()
    return application


def ensure_revision(application: Application, revision: int) -> None:
    if application.revision != revision:
        raise AppError(
            ErrorCode.REVISION_CONFLICT,
            "Заявка изменилась, обновите данные",
            RevisionConflictDetails(current_revision=application.revision),
        )


async def lock_any(session: AsyncSession, application_id: uuid.UUID) -> Application:
    """Блокировка для менеджера: любая заявка, но черновик менеджеру не виден (404)."""
    application = await session.scalar(
        select(Application)
        .where(Application.id == application_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if application is None or application.status == "DRAFT":
        raise _not_found()
    return application


async def get_any(session: AsyncSession, application_id: uuid.UUID) -> Application:
    application = await session.get(Application, application_id)
    if application is None or application.status == "DRAFT":
        raise _not_found()
    return application
