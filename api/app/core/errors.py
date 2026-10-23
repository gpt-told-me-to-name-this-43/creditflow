"""Единый формат ошибок API (design.md §3.7) и описание ошибок для OpenAPI.

Любая ошибка — включая 422 Pydantic и 404 несуществующего маршрута — уходит клиенту
как `ErrorEnvelope`. Бизнес-код бросает `AppError(ErrorCode.X)`; HTTP-статус берётся
из `ERROR_STATUS`, поэтому код и статус не могут разойтись.
"""

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import (
    DETAILS_MODELS,
    ERROR_STATUS,
    ErrorBody,
    ErrorCode,
    ErrorDetails,
    ErrorEnvelope,
    TooManyAttemptsDetails,
    ValidationDetail,
    ValidationDetails,
)

logger = logging.getLogger("app.errors")

# HTTPException без бизнес-кода (Starlette, будущие middleware) → код по статусу.
# RequestValidationError обрабатывается отдельно. Неизвестный 4xx нормализуется
# в 400 BAD_REQUEST, неизвестный 5xx — в 500 INTERNAL_ERROR.
_HTTP_FALLBACK = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.TOO_MANY_ATTEMPTS,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


def http_error_code(status_code: int) -> ErrorCode:
    if status_code in _HTTP_FALLBACK:
        return _HTTP_FALLBACK[status_code]
    return ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.BAD_REQUEST


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | ErrorDetails | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details
        self.headers = headers

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.code]


def error_response(
    status_code: int, body: ErrorBody, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    content = ErrorEnvelope(error=body).model_dump(mode="json", exclude_none=True)
    merged = dict(headers or {})
    if isinstance(body.details, TooManyAttemptsDetails):
        if body.details.scope == "SIGN_ATTEMPTS":
            merged = {key: value for key, value in merged.items() if key.lower() != "retry-after"}
        elif body.details.retry_after_seconds is not None:
            merged = {key: value for key, value in merged.items() if key.lower() != "retry-after"}
            merged["Retry-After"] = str(body.details.retry_after_seconds)
    if status_code == 401:
        merged.setdefault("WWW-Authenticate", "Bearer")
    return JSONResponse(status_code=status_code, content=content, headers=merged or None)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(
            exc.status_code,
            ErrorBody(
                code=exc.code,
                message=exc.message,
                details=exc.details,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Не возвращаем input/ctx: там могут находиться пароль и персональные данные.
        fields = []
        headers = {
            "idempotency-key": "Idempotency-Key",
            "authorization": "Authorization",
            "x-test-reset-token": "X-Test-Reset-Token",
        }
        ranges = {"greater_than", "greater_than_equal", "less_than", "less_than_equal"}
        for error in exc.errors():
            loc = [str(part) for part in error["loc"]]
            if (
                len(loc) > 1
                and loc[0] == "body"
                and isinstance(exc.body, dict)
                and loc[1] == exc.body.get("action")
            ):
                # Метка discriminated union не является именем поля JSON.
                loc.pop(1)
            if len(loc) > 1 and loc[0] == "header":
                loc[1] = headers.get(loc[1].lower(), loc[1])
            kind = error["type"]
            code = "OUT_OF_RANGE" if kind in ranges else kind.upper()
            fields.append(ValidationDetail(field=".".join(loc), code=code, message=error["msg"]))
        body = ErrorBody(
            code=ErrorCode.VALIDATION_ERROR,
            message="Некорректный запрос",
            details=ValidationDetails(fields=fields),
        )
        return error_response(422, body)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Инвариант контракта: HTTP-статус ответа == ERROR_STATUS[code]. Неизвестный статус
        # нормализуется к статусу своего кода (418 → 400 BAD_REQUEST, 502 → 500
        # INTERNAL_ERROR), исходный — в лог. Заголовки (Allow у 405, Retry-After у 429)
        # сохраняются.
        code = http_error_code(exc.status_code)
        status = ERROR_STATUS[code]
        if status != exc.status_code:
            logger.warning("HTTP %s без кода в контракте → %s %s", exc.status_code, status, code)
        body = ErrorBody(code=code, message=str(exc.detail))
        return error_response(status, body, getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Трассировка — в лог uvicorn; клиенту — конверт без деталей исключения.
        logger.exception("unhandled error", exc_info=exc)
        body = ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="Внутренняя ошибка сервера")
        return error_response(500, body)


_DESCRIPTIONS = {
    401: "Нет или недействителен токен",
    403: "Недостаточно прав для роли",
    404: "Объект не найден или принадлежит другому клиенту",
    409: "Конфликт состояния",
    422: "Ошибка валидации или бизнес-правила",
    429: "Слишком много попыток",
    500: "Внутренняя ошибка сервера",
    503: "Сервис или внешний источник временно недоступен",
}


_MESSAGES = {
    ErrorCode.UNAUTHORIZED: "Войдите заново",
    ErrorCode.INVALID_CREDENTIALS: "Неверный логин или пароль",
    ErrorCode.FORBIDDEN: "Недостаточно прав",
    ErrorCode.APPLICANT_NOT_AUTHORIZED: (
        "Подать заявку может только руководитель компании или сам ИП"
    ),
    ErrorCode.NOT_FOUND: "Не найдено",
    ErrorCode.REVISION_CONFLICT: "Заявка изменилась, обновите страницу",
    ErrorCode.INVALID_STATUS_TRANSITION: "Действие недоступно в текущем статусе заявки",
    ErrorCode.IDEMPOTENCY_IN_PROGRESS: "Запрос уже обрабатывается, подождите",
    ErrorCode.COMPANY_ALREADY_BOUND: "Компания уже привязана",
    ErrorCode.USER_ALREADY_BOUND: "К учётной записи уже привязана компания",
    ErrorCode.COMPANY_NOT_BOUND: "Привяжите компанию",
    ErrorCode.APPLICATION_INCOMPLETE: "Заполнены не все обязательные поля",
    ErrorCode.PRODUCT_NOT_ELIGIBLE: "Продукт не подходит для условий заявки",
    ErrorCode.SIGN_CHALLENGE_EXPIRED: "Запросите новый код подтверждения",
    ErrorCode.VALIDATION_ERROR: "Некорректный запрос",
    ErrorCode.INVALID_INN: "Проверьте ИНН",
    ErrorCode.COMPANY_NOT_IN_REGISTRY: "Компания не найдена в реестре",
    ErrorCode.CONSENT_REQUIRED: "Подтвердите согласие",
    ErrorCode.ACTION_NOT_ALLOWED: "Действие недоступно для этой заявки",
    ErrorCode.AMOUNT_ABOVE_LIMIT: "Сумма превышает доступный лимит на этот срок",
    ErrorCode.SIGN_CODE_INVALID: "Неверный код подтверждения",
    ErrorCode.IDEMPOTENCY_KEY_REUSED: "Повторите действие с новым ключом",
    ErrorCode.TOO_MANY_ATTEMPTS: "Слишком много попыток, попробуйте позже",
    ErrorCode.PROVIDER_UNAVAILABLE: "Внешний сервис недоступен, повторите позже",
    ErrorCode.INTERNAL_ERROR: "Что-то пошло не так, повторите позже",
    ErrorCode.SERVICE_UNAVAILABLE: "Сервис временно недоступен, повторите позже",
}


_EXAMPLE_DETAILS: dict[ErrorCode, dict[str, Any]] = {
    ErrorCode.VALIDATION_ERROR: {
        "fields": [
            {
                "field": "body.requested_amount_rub",
                "code": "OUT_OF_RANGE",
                "message": "Значение вне допустимого диапазона",
            }
        ]
    },
    ErrorCode.APPLICATION_INCOMPLETE: {"missing_fields": ["term_months", "product_id"]},
    ErrorCode.PRODUCT_NOT_ELIGIBLE: {
        "product_id": "working_capital",
        "unmet_constraints": ["PURPOSE_NOT_ALLOWED", "TERM_ABOVE_PRODUCT_MAX"],
    },
    ErrorCode.REVISION_CONFLICT: {"current_revision": 4},
    ErrorCode.SIGN_CODE_INVALID: {"remaining_attempts": 2},
    ErrorCode.TOO_MANY_ATTEMPTS: {"scope": "LOGIN", "retry_after_seconds": 60},
}


def example_details(code: ErrorCode, *, signing: bool = False) -> Any:
    value = _EXAMPLE_DETAILS.get(code)
    if signing and code is ErrorCode.TOO_MANY_ATTEMPTS:
        value = {"scope": "SIGN_ATTEMPTS"}
    if value is None:
        return None
    return DETAILS_MODELS[code].model_validate(value)


def errors(
    *codes: ErrorCode,
    public: bool = False,
    role: bool = True,
    not_found: bool = True,
    validation: bool = True,
    signing: bool = False,
    challenge: bool = False,
) -> dict[int | str, dict[str, Any]]:
    """`responses=`: применимые 401/403/404/422 и переданные бизнес-коды.

    Общие 500/503 описаны отдельно от доменных ошибок; наличие 503 не означает
    вызов ext-sim. signing добавляет счётчик попыток в примеры ошибок подписания.
    """
    by_status: dict[int, list[ErrorCode]] = {
        500: [ErrorCode.INTERNAL_ERROR],
        503: [ErrorCode.SERVICE_UNAVAILABLE],
    }
    if not_found:
        by_status[404] = [ErrorCode.NOT_FOUND]
    if validation:
        by_status[422] = [ErrorCode.VALIDATION_ERROR]
    if not public:
        by_status[401] = [ErrorCode.UNAUTHORIZED]
        if role:
            by_status[403] = [ErrorCode.FORBIDDEN]
    for code in codes:
        bucket = by_status.setdefault(ERROR_STATUS[code], [])
        if code not in bucket:
            bucket.append(code)
    return {
        status: {
            "model": ErrorEnvelope,
            "description": f"{_DESCRIPTIONS[status]}: {', '.join(c.value for c in found)}",
            **(
                {
                    "headers": {
                        "WWW-Authenticate": {
                            "description": "Схема аутентификации",
                            "schema": {"type": "string"},
                            "example": "Bearer",
                        }
                    }
                }
                if status == 401
                else {}
            ),
            **(
                {
                    "headers": {
                        "Retry-After": {
                            "description": "Целые секунды; отсутствует при scope SIGN_ATTEMPTS",
                            "schema": {"type": "integer", "minimum": 0},
                            "example": 60,
                        }
                    }
                }
                if status == 429 and not signing
                else {}
            ),
            "content": {
                "application/json": {
                    "examples": {
                        code.value: {
                            "value": ErrorEnvelope(
                                error=ErrorBody(
                                    code=code,
                                    message=_MESSAGES[code],
                                    details=(
                                        {"scope": "CHALLENGE_ISSUE", "retry_after_seconds": 60}
                                        if challenge and code is ErrorCode.TOO_MANY_ATTEMPTS
                                        else example_details(code, signing=signing)
                                    ),
                                )
                            ).model_dump(mode="json", exclude_none=True)
                        }
                        for code in found
                    }
                }
            },
        }
        for status, found in sorted(by_status.items())
    }
