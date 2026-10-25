"""Bearer-токен, текущий пользователь и роль.

`require_bearer` — форма контракта #6 для ещё не реализованных стабов: проверяет лишь
наличие заголовка `Authorization: Bearer <что угодно>`. Поэтому защищённые стабы
не монтируются при APP_ENV=production (`app.main.create_app`).

`current_user` — проверка JWT HS256 для реализованных маршрутов (#7). Токен подписан
`APP_SECRET_KEY`, в `sub` — id пользователя, роль и компания читаются из БД на каждый
запрос (привязка компании могла измениться после выдачи токена). Выдачу токена через
`POST /auth/login`, rate limit и проверку силы ключа добавляет #5; до этого токен для
ручной проверки выпускает `scripts/dev_token.py` через `encode_token`.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.db import sessionmaker_of
from app.core.errors import AppError
from app.db.models import User
from app.schemas.auth import Role
from app.schemas.common import ErrorCode

TOKEN_TTL_SECONDS = 8 * 3600  # design §4: TTL 8 ч, без refresh

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


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, signing_input: str) -> str:
    return _b64(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest())


def encode_token(
    user_id: uuid.UUID, role: Role, secret: str, *, ttl: int = TOKEN_TTL_SECONDS
) -> str:
    if not secret:
        raise ValueError("APP_SECRET_KEY не задан: токен не выпускается")
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    claims = {"sub": str(user_id), "role": role.value, "iat": now, "exp": now + ttl}
    payload = _b64(json.dumps(claims).encode())
    return f"{header}.{payload}.{_sign(secret, f'{header}.{payload}')}"


def decode_token(token: str, secret: str) -> dict[str, Any] | None:
    """Claims валидного неистёкшего токена, иначе None. Причину отказа не раскрываем."""
    if not secret:
        return None
    try:
        header, payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _sign(secret, f"{header}.{payload}")):
            return None
        if json.loads(_unb64(header)).get("alg") != "HS256":
            return None
        claims: dict[str, Any] = json.loads(_unb64(payload))
    except ValueError:
        return None
    if not isinstance(claims.get("exp"), int) or claims["exp"] <= time.time():
        return None
    return claims


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    role: Role
    full_name: str
    company_id: uuid.UUID | None


async def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)],
) -> CurrentUser:
    if credentials is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Требуется Bearer-токен")
    settings: Settings = request.app.state.settings
    claims = decode_token(credentials.credentials, settings.app_secret_key)
    try:
        user_id = uuid.UUID(str(claims["sub"])) if claims else None
    except ValueError:
        user_id = None
    if user_id is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Токен недействителен")
    # Отдельная короткая сессия: сессия обработчика остаётся без открытой транзакции,
    # и сервис сам начинает её через `session.begin()`.
    async with sessionmaker_of(request)() as session:
        user = await session.get(User, user_id)
    if user is None:
        raise AppError(ErrorCode.UNAUTHORIZED, "Токен недействителен")
    return CurrentUser(user.id, Role(user.role), user.full_name, user.company_id)


def require_role(role: Role) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    async def check(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.role is not role:
            raise AppError(ErrorCode.FORBIDDEN, "Недостаточно прав")
        return user

    return check


require_client = require_role(Role.CLIENT)
require_manager = require_role(Role.MANAGER)


async def bound_client(
    user: Annotated[CurrentUser, Depends(require_client)],
) -> CurrentUser:
    """Клиент с привязанной компанией; без неё `/applications*` — 409 COMPANY_NOT_BOUND."""
    if user.company_id is None:
        raise AppError(ErrorCode.COMPANY_NOT_BOUND, "Сначала привяжите компанию")
    return user


Client = Annotated[CurrentUser, Depends(require_client)]
BoundClient = Annotated[CurrentUser, Depends(bound_client)]
Manager = Annotated[CurrentUser, Depends(require_manager)]
CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
