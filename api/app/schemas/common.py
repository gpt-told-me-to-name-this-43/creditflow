"""Общие типы контракта API v1 (design.md §3.7, issue #6).

- Деньги и DSCR в API — строки: `float` в JSON теряет копейки, а `number` в OpenAPI
  превратится во фронте в JS-number. Входные суммы — целые рубли (`int`, gt=0).
- Ошибки — единый конверт `{"error": {"code", "message", "details?"}}`; список кодов —
  `ErrorCode`, таблица для пользователя — `docs/api.md` (тест сверяет одно с другим).
"""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Money = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$", examples=["117698.56"])]
MoneyStr = Annotated[str, Field(pattern=r"^\d+\.\d{2}$", examples=["100000.00"])]
Dscr = Annotated[str, Field(pattern=r"^-?\d+\.\d{2}$", examples=["1.10"])]  # ROUND_DOWN
AmountRub = Annotated[int, Field(strict=True, gt=0, examples=[3000000])]  # вход: целые рубли
Revision = Annotated[
    int, Field(strict=True, ge=0, description="Текущая revision заявки (409 при расхождении)")
]


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
    COMPANY_NOT_BOUND = "COMPANY_NOT_BOUND"
    # 422
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_INN = "INVALID_INN"
    COMPANY_NOT_IN_REGISTRY = "COMPANY_NOT_IN_REGISTRY"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"
    APPLICATION_INCOMPLETE = "APPLICATION_INCOMPLETE"
    PRODUCT_NOT_ELIGIBLE = "PRODUCT_NOT_ELIGIBLE"
    SIGN_CHALLENGE_EXPIRED = "SIGN_CHALLENGE_EXPIRED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    AMOUNT_ABOVE_LIMIT = "AMOUNT_ABOVE_LIMIT"
    SIGN_CODE_INVALID = "SIGN_CODE_INVALID"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    # 429
    TOO_MANY_ATTEMPTS = "TOO_MANY_ATTEMPTS"
    # 503 — только сбой ext-sim
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    # Инфраструктурные HTTP-ошибки без бизнес-кода (Starlette/прокси/необработанное исключение).
    # Отдельные коды, чтобы фронт не принял их за ошибку валидации формы.
    BAD_REQUEST = "BAD_REQUEST"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


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
    ErrorCode.COMPANY_NOT_BOUND: 409,
    ErrorCode.APPLICATION_INCOMPLETE: 422,
    ErrorCode.PRODUCT_NOT_ELIGIBLE: 422,
    ErrorCode.SIGN_CHALLENGE_EXPIRED: 422,
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
    ErrorCode.BAD_REQUEST: 400,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
}


class ProductConstraint(StrEnum):
    PURPOSE_NOT_ALLOWED = "PURPOSE_NOT_ALLOWED"
    AMOUNT_BELOW_PRODUCT_MIN = "AMOUNT_BELOW_PRODUCT_MIN"
    AMOUNT_ABOVE_PRODUCT_MAX = "AMOUNT_ABOVE_PRODUCT_MAX"
    TERM_BELOW_PRODUCT_MIN = "TERM_BELOW_PRODUCT_MIN"
    TERM_ABOVE_PRODUCT_MAX = "TERM_ABOVE_PRODUCT_MAX"


class ValidationDetail(Schema):
    field: str = Field(description="Путь body/query/path/header через точку; индексы с нуля")
    code: str = Field(examples=["OUT_OF_RANGE"])
    message: str


class ValidationDetails(Schema):
    fields: list[ValidationDetail]


class ApplicationIncompleteDetails(Schema):
    missing_fields: list[str]


class ProductNotEligibleDetails(Schema):
    product_id: str
    unmet_constraints: list[ProductConstraint]


class RevisionConflictDetails(Schema):
    current_revision: Revision


class SignCodeInvalidDetails(Schema):
    remaining_attempts: int = Field(strict=True, ge=0, le=2)


class TooManyAttemptsDetails(Schema):
    scope: Literal["LOGIN", "SIGN_ATTEMPTS", "CHALLENGE_ISSUE"]
    retry_after_seconds: int | None = Field(default=None, strict=True, ge=0)

    @model_validator(mode="after")
    def _scope(self) -> Self:
        if self.scope == "SIGN_ATTEMPTS" and self.retry_after_seconds is not None:
            raise ValueError("SIGN_ATTEMPTS не задаёт Retry-After: нужен новый challenge")
        return self


ErrorDetails = (
    ValidationDetails
    | ApplicationIncompleteDetails
    | ProductNotEligibleDetails
    | RevisionConflictDetails
    | SignCodeInvalidDetails
    | TooManyAttemptsDetails
)

DETAILS_MODELS: dict[ErrorCode, type[Schema]] = {
    ErrorCode.VALIDATION_ERROR: ValidationDetails,
    ErrorCode.APPLICATION_INCOMPLETE: ApplicationIncompleteDetails,
    ErrorCode.PRODUCT_NOT_ELIGIBLE: ProductNotEligibleDetails,
    ErrorCode.REVISION_CONFLICT: RevisionConflictDetails,
    ErrorCode.SIGN_CODE_INVALID: SignCodeInvalidDetails,
    ErrorCode.TOO_MANY_ATTEMPTS: TooManyAttemptsDetails,
}


class ErrorBody(Schema):
    code: ErrorCode
    message: str
    details: ErrorDetails | None = None

    @model_validator(mode="after")
    def _details_match_code(self) -> Self:
        if self.details is not None and type(self.details) is not DETAILS_MODELS.get(self.code):
            raise ValueError("Тип details не соответствует ErrorCode")
        return self


class ErrorEnvelope(Schema):
    error: ErrorBody
