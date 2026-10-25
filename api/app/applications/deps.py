"""Зависимости маршрутов конвейера (#7) поверх доступа #5 (`app.auth.deps`)."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.deps import CurrentUser, require_role
from app.core.db import get_db
from app.core.errors import AppError
from app.core.idempotency import Idempotency, idempotent
from app.schemas.auth import Role
from app.schemas.common import ErrorCode

require_client = require_role(Role.CLIENT)
require_manager = require_role(Role.MANAGER)


async def bound_client(user: Annotated[CurrentUser, Depends(require_client)]) -> CurrentUser:
    """Клиент с привязанной компанией; без неё `/applications*` — 409 COMPANY_NOT_BOUND."""
    if user.company_id is None:
        raise AppError(ErrorCode.COMPANY_NOT_BOUND, "Привяжите компанию")
    return user


def session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


DbSession = Annotated[AsyncSession, Depends(get_db)]
BoundClient = Annotated[CurrentUser, Depends(bound_client)]
Manager = Annotated[CurrentUser, Depends(require_manager)]
Idem = Annotated[Idempotency, Depends(idempotent)]
