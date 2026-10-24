"""Bearer-контракт #6 — только форма, НЕ аутентификация.

`require_bearer` проверяет лишь наличие заголовка `Authorization: Bearer <что угодно>`:
подпись, срок, пользователь и роль не проверяются, RBAC нет. Этого достаточно, чтобы
фронт генерировал клиент с securitySchemes и получал 401 без заголовка, но не для
защиты данных. Поэтому защищённые стабы не монтируются при APP_ENV=production
(`app.main.create_app`). Проверку JWT HS256 и `require_role` добавляет #5.
"""

from typing import Annotated

from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.schemas.common import ErrorCode

bearer = HTTPBearer(
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description=(
        "JWT HS256 из POST /auth/login. В контракте #6 сервер проверяет только наличие "
        "Bearer-заголовка; подпись, срок и роль проверяются начиная с #5."
    ),
    auto_error=False,
)


async def require_bearer(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> None:
    if credentials is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Требуется Bearer-токен")
