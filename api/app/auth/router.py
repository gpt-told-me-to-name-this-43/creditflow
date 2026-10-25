"""Вход и текущий пользователь (#5, design.md §3.3). Монтируется во всех окружениях.

Неверный логин и неверный пароль неразличимы: одинаковый `401 INVALID_CREDENTIALS`, и для
несуществующего логина тоже выполняется проверка argon2 (по фиктивному хешу), поэтому
время ответа не выдаёт, есть ли учётка.
"""

from typing import Annotated
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.examples import EXAMPLE_ID, attach_examples, example_from
from app.auth.deps import CurrentUserDep
from app.auth.tokens import TOKEN_TTL, issue_token
from app.core.config import Settings
from app.core.db import get_db
from app.core.errors import AppError, errors
from app.core.logs import get_logger
from app.core.ratelimit import RateLimits, rate_limits, too_many_attempts
from app.core.security import client_ip
from app.db.models import User
from app.schemas.auth import DemoAccount, LoginRequest, Me, Role, TokenResponse
from app.schemas.common import ErrorCode as E
from app.seed import DEMO_PASSWORD, DEMO_USERS

logger = get_logger("app.auth")

_hasher = PasswordHasher()
# Хеш случайной строки с теми же параметрами argon2, что у учёток (app/seed.py).
_DUMMY_HASH = _hasher.hash("creditflow-no-such-user")

router = APIRouter(prefix="/auth", tags=["auth"])


def app_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


AppSettings = Annotated[Settings, Depends(app_settings)]
Session = Annotated[AsyncSession, Depends(get_db)]
Limits = Annotated[RateLimits, Depends(rate_limits)]


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _build_login() -> TokenResponse:
    return TokenResponse(access_token="stub.jwt.token", expires_in=8 * 3600)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=errors(E.INVALID_CREDENTIALS, E.TOO_MANY_ATTEMPTS, public=True, not_found=False),
)
@example_from(_build_login)
async def login(
    body: LoginRequest, request: Request, settings: AppSettings, session: Session, limits: Limits
) -> TokenResponse:
    if not settings.load_test_enabled:
        retry_after = limits.login_ip.acquire(client_ip(request))
        if retry_after is not None:
            raise too_many_attempts("LOGIN", retry_after)
    login_key = body.login.strip().casefold()
    retry_after = limits.login_failures.acquire(login_key)
    if retry_after is not None:
        raise too_many_attempts("LOGIN", retry_after)
    try:
        user = (
            await session.execute(
                select(User.id, User.role, User.password_hash).where(
                    func.lower(User.email) == login_key
                )
            )
        ).one_or_none()
        # argon2 занимает процессор ~десятки мс: в пуле потоков, чтобы не блокировать
        # event loop.
        valid = await run_in_threadpool(
            _verify, user.password_hash if user else _DUMMY_HASH, body.password
        )
    except BaseException:
        limits.login_failures.release(login_key)
        raise
    if user is None or not valid:
        limits.login_failures.failure(login_key)
        logger.info("login failed")
        raise AppError(E.INVALID_CREDENTIALS, "Неверный логин или пароль")
    limits.login_failures.success(login_key)
    logger.info("login ok", user_id=str(user.id), role=user.role)
    token = issue_token(user.id, user.role, settings.app_secret_key)
    return TokenResponse(access_token=token, expires_in=int(TOKEN_TTL.total_seconds()))


def _build_me() -> Me:
    return Me(
        id=UUID(EXAMPLE_ID),
        role=Role.CLIENT,
        full_name="Кузнецова Анна Михайловна",
        company_id=None,
    )


@router.get(
    "/me",
    response_model=Me,
    responses=errors(role=False, not_found=False, validation=False),
)
@example_from(_build_me)
async def me(user: CurrentUserDep) -> Me:
    return Me(id=user.id, role=user.role, full_name=user.full_name, company_id=user.company_id)


def _build_demo_accounts() -> list[DemoAccount]:
    return [
        DemoAccount(
            login=user.email,
            password=DEMO_PASSWORD,
            role=Role(user.role),
            label=user.full_name,
            scenario=(f"C{i + 1}" if i < 7 else "Отказ полномочий" if i == 7 else "MANAGER"),
        )
        for i, user in enumerate(DEMO_USERS)
    ]


@router.get(
    "/demo-accounts",
    response_model=list[DemoAccount],
    responses=errors(public=True, validation=False),
    description="Публичный маршрут. При DEMO_AUTH_ENABLED=false возвращает 404.",
)
@example_from(_build_demo_accounts)
async def demo_accounts(settings: AppSettings) -> list[DemoAccount]:
    if not settings.demo_auth_enabled:
        raise AppError(E.NOT_FOUND, "Not Found")
    return _build_demo_accounts()


attach_examples((router,))
