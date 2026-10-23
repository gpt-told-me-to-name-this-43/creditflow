"""Bearer-контракт #6. Проверка JWT и RBAC заменяет эту зависимость в #5."""

from typing import Annotated

from fastapi import Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.errors import AppError
from app.schemas.common import ErrorCode

bearer = HTTPBearer(
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description="JWT HS256 из POST /auth/login. Проверка подписи и роли — задача #5.",
    auto_error=False,
)


async def require_bearer(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> None:
    if credentials is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Требуется Bearer-токен")
