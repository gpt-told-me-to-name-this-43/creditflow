"""Общие типы контракта API v1 (design.md §3.7, issue #6).

- Деньги и DSCR в API — строки: `float` в JSON теряет копейки, а `number` в OpenAPI
  превратится во фронте в JS-number. Входные суммы — целые рубли (`int`, gt=0).
- Ошибки — единый конверт `{"error": {"code", "message", "details?"}}`; список кодов —
  `ErrorCode`, таблица для пользователя — `docs/api.md` (тест сверяет одно с другим).
"""

from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$", examples=["117698.56"])]
Dscr = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$", examples=["1.10"])]  # ROUND_DOWN
AmountRub = Annotated[int, Field(gt=0, examples=[3000000])]  # вход: целые рубли
Revision = Annotated[int, Field(ge=0, description="Текущая revision заявки (409 при расхождении)")]


class Schema(BaseModel):
    """База DTO: лишние поля во входе — 422, а не молчаливое игнорирование."""

    model_config = ConfigDict(extra="forbid")


class ErrorCode(StrEnum):
    # 401 / 403
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    FORBIDDEN = "FORBIDDEN"
    APPLICANT_NOT_AUTHORIZED = "APPLICANT_NOT_AUTHORIZED"
    # 404
    NOT_FOUND = "NOT_FOUND"
    # 409
    REVISION_CONFLICT = "REVISION_CONFLICT"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    IDEMPOTENCY_IN_PROGRESS = "IDEMPOTENCY_IN_PROGRESS"
    COMPANY_ALREADY_BOUND = "COMPANY_ALREADY_BOUND"
    USER_ALREADY_BOUND = "USER_ALREADY_BOUND"
    # 422
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INN = "INVALID_INN"
    COMPANY_NOT_IN_REGISTRY = "COMPANY_NOT_IN_REGISTRY"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    AMOUNT_ABOVE_LIMIT = "AMOUNT_ABOVE_LIMIT"
    SIGN_CODE_INVALID = "SIGN_CODE_INVALID"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    # 429
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    # 503 — только сбой ext-sim
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"


ERROR_STATUS: dict[ErrorCode, int] = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.APPLICANT_NOT_AUTHORIZED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.REVISION_CONFLICT: 409,
    ErrorCode.INVALID_STATUS_TRANSITION: 409,
    ErrorCode.IDEMPOTENCY_IN_PROGRESS: 409,
    ErrorCode.COMPANY_ALREADY_BOUND: 409,
    ErrorCode.USER_ALREADY_BOUND: 409,
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.INVALID_INN: 422,
    ErrorCode.COMPANY_NOT_IN_REGISTRY: 422,
    ErrorCode.CONSENT_REQUIRED: 422,
    ErrorCode.ACTION_NOT_ALLOWED: 422,
    ErrorCode.AMOUNT_ABOVE_LIMIT: 422,
    ErrorCode.SIGN_CODE_INVALID: 422,
    ErrorCode.IDEMPOTENCY_KEY_REUSED: 422,
    ErrorCode.TOO_MANY_ATTEMPTS: 429,
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
}


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorBody
