"""`POST /_test/reset?mode=clean|demo` — служебный сброс для e2e (design.md §4).

Контракт #6; сама очистка БД и загрузка демо-состояния — в #7 (`make demo-reset`).

- Роутер монтируется только при `TEST_RESET_ENABLED=true` (иначе 404 и нет в OpenAPI);
  в production включённый флаг уже роняет старт (`Settings`).
- Требуется `X-Test-Reset-Token`, равный `TEST_RESET_TOKEN` (≥ 32 байт), сравнение за
  постоянное время. Любое несовпадение — и отсутствие/короткий токен в конфиге — даёт
  обычный 404 `NOT_FOUND`: эндпоинт не раскрывается.
"""

import hmac
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.security import APIKeyHeader

from app.core.config import Settings
from app.core.errors import AppError, errors
from app.schemas.common import ErrorCode, Schema

logger = logging.getLogger("app.test_reset")

MIN_TOKEN_BYTES = 32

reset_token = APIKeyHeader(
    name="X-Test-Reset-Token", scheme_name="TestResetToken", auto_error=False
)


class TestResetResult(Schema):
    __test__ = False  # не тестовый класс для pytest, несмотря на имя

    mode: Literal["clean", "demo"]


def _token_ok(expected: str | None, given: str | None) -> bool:
    if expected is None or len(expected.encode()) < MIN_TOKEN_BYTES or given is None:
        return False  # fail-closed: без годного токена в конфиге эндпоинт недоступен
    return hmac.compare_digest(expected.encode(), given.encode())


async def require_reset_token(
    request: Request,
    token: Annotated[str | None, Security(reset_token)],
) -> None:
    settings: Settings = request.app.state.settings
    if not _token_ok(settings.test_reset_token, token):
        logger.warning("test reset: rejected")
        raise AppError(ErrorCode.NOT_FOUND, "Not Found")


router = APIRouter(prefix="/_test", tags=["service"], dependencies=[Depends(require_reset_token)])


@router.post(
    "/reset",
    response_model=TestResetResult,
    responses={
        **errors(public=True),
        200: {"content": {"application/json": {"example": {"mode": "clean"}}}},
    },
    description="Только local/test при TEST_RESET_ENABLED=true и TEST_RESET_TOKEN ≥ 32 байт. "
    "Контрактный стаб: возвращает выбранный mode, очистка БД и seed реализуются в #7.",
)
async def reset(
    mode: Annotated[Literal["clean", "demo"], Query(examples=["clean", "demo"])],
) -> TestResetResult:
    logger.info("test reset: mode=%s (стаб #6, очистка — в #7)", mode)
    return TestResetResult(mode=mode)
