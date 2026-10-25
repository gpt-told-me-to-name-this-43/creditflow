"""Зависимости доступа (#5): `current_user`, `require_role`, `get_owned_application`.

- `current_user` — JWT → `CurrentUser`. Пользователь читается из БД на каждый запрос:
  роль, компания и само существование учётки берутся из БД, а не из payload. Токен
  удалённого пользователя или с ролью, не совпадающей с БД, — `401 UNAUTHORIZED`.
- `require_role(*roles)` — для `APIRouter(dependencies=[...])`; не та роль — `403 FORBIDDEN`.
- `get_owned_application` — заявка текущего клиента по `application_id`; без компании —
  `409 COMPANY_NOT_BOUND`, чужая или несуществующая — `404 NOT_FOUND`.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.tokens import InvalidTokenError, decode_token
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.request_context import set_access_log_field
from app.core.security import bearer
from app.db.models import Application, User
from app.schemas.auth import Role
from app.schemas.common import ErrorCode


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    role: Role
    full_name: str
    person_inn: str | None
    company_id: uuid.UUID | None


def _unauthorized() -> AppError:
    return AppError(ErrorCode.UNAUTHORIZED, "Требуется вход")


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> CurrentUser:
    if credentials is None:
        raise _unauthorized()
    settings: Settings = request.app.state.settings
    try:
        claims = decode_token(credentials.credentials, settings.app_secret_key)
    except InvalidTokenError:
        raise _unauthorized() from None
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = (
            await session.execute(
                select(User.id, User.role, User.full_name, User.person_inn, User.company_id).where(
                    User.id == claims.user_id
                )
            )
        ).one_or_none()
    if row is None or row.role != claims.role:
        raise _unauthorized()
    user = CurrentUser(
        id=row.id,
        role=Role(row.role),
        full_name=row.full_name,
        person_inn=row.person_inn,
        company_id=row.company_id,
    )
    set_access_log_field("user_id", str(user.id))
    set_access_log_field("role", user.role.value)
    return user


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]


def require_role(*roles: Role) -> Callable[..., Awaitable[CurrentUser]]:
    if not roles:
        raise ValueError("require_role: нужна хотя бы одна роль")
    allowed = frozenset(roles)

    async def check_role(user: CurrentUserDep) -> CurrentUser:
        if user.role not in allowed:
            raise AppError(ErrorCode.FORBIDDEN, "Недостаточно прав")
        return user

    return check_role


async def get_owned_application(
    application_id: uuid.UUID,
    user: CurrentUserDep,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Application:
    if user.role is not Role.CLIENT:
        raise AppError(ErrorCode.FORBIDDEN, "Недостаточно прав")
    if user.company_id is None:
        raise AppError(ErrorCode.COMPANY_NOT_BOUND, "Привяжите компанию")
    application = await session.scalar(
        select(Application).where(
            Application.id == application_id, Application.owner_user_id == user.id
        )
    )
    if application is None:
        raise AppError(ErrorCode.NOT_FOUND, "Не найдено")
    return application
