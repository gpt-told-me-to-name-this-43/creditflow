"""Единый формат ошибок API (design.md §3.7) и описание ошибок для OpenAPI.

Любая ошибка — включая 422 Pydantic и 404 несуществующего маршрута — уходит клиенту
как `ErrorEnvelope`. Бизнес-код бросает `AppError(ErrorCode.X)`; HTTP-статус берётся
из `ERROR_STATUS`, поэтому код и статус не могут разойтись.
"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.schemas.common import ERROR_STATUS, ErrorBody, ErrorCode, ErrorEnvelope

_HTTP_FALLBACK = {401: ErrorCode.UNAUTHORIZED, 403: ErrorCode.FORBIDDEN, 404: ErrorCode.NOT_FOUND}


class AppError(Exception):
    def __init__(
        self, code: ErrorCode, message: str, details: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    @property
    def status_code(self) -> int:
        return ERROR_STATUS[self.code]


def error_response(status_code: int, body: ErrorBody) -> JSONResponse:
    content = ErrorEnvelope(error=body).model_dump(mode="json", exclude_none=True)
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return error_response(
            exc.status_code, ErrorBody(code=exc.code, message=exc.message, details=exc.details)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # во входе могут быть пароли/тексты клиента: отдаём только loc/msg/type, без input
        details = [
            {"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()
        ]
        body = ErrorBody(
            code=ErrorCode.VALIDATION_ERROR, message="Некорректный запрос", details=details
        )
        return error_response(422, body)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_FALLBACK.get(exc.status_code, ErrorCode.VALIDATION_ERROR)
        return error_response(exc.status_code, ErrorBody(code=code, message=str(exc.detail)))


_DESCRIPTIONS = {
    401: "Нет или недействителен токен",
    403: "Недостаточно прав для роли",
    404: "Объект не найден или принадлежит другому клиенту",
    409: "Конфликт состояния",
    422: "Ошибка валидации или бизнес-правила",
    429: "Слишком много попыток",
    503: "Внешний сервис (ext-sim) недоступен",
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
}


def errors(*codes: ErrorCode, public: bool = False) -> dict[int | str, dict[str, Any]]:
    """`responses=`: 404/422 и статусы переданных кодов; для защищённых также 401/403.

    В описание статуса попадают конкретные `code` — фронт видит их в Swagger и в типах.
    """
    by_status: dict[int, list[ErrorCode]] = {
        404: [ErrorCode.NOT_FOUND],
        422: [ErrorCode.VALIDATION_ERROR],
    }
    if not public:
        by_status.update({401: [ErrorCode.UNAUTHORIZED], 403: [ErrorCode.FORBIDDEN]})
    for code in codes:
        bucket = by_status.setdefault(ERROR_STATUS[code], [])
        if code not in bucket:
            bucket.append(code)
    return {
        status: {
            "model": ErrorEnvelope,
            "description": f"{_DESCRIPTIONS[status]}: {', '.join(c.value for c in found)}",
            "content": {
                "application/json": {
                    "examples": {
                        code.value: {
                            "value": ErrorEnvelope(
                                error=ErrorBody(
                                    code=code,
                                    message=_MESSAGES[code],
                                    details=[
                                        {
                                            "loc": ["body", "revision"],
                                            "msg": "Field required",
                                            "type": "missing",
                                        }
                                    ]
                                    if code is ErrorCode.VALIDATION_ERROR
                                    else None,
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
