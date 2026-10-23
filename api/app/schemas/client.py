"""DTO клиентского кабинета (design.md §3.3).

Запрет issue #6: клиент никогда не видит score, DSCR, лимит, коды, проект решения,
AI-заключение и комментарий менеджера. Поэтому это ОТДЕЛЬНЫЕ классы, а не менеджерские
с `exclude`: запрещённых полей здесь нет физически. Тест `test_client_schemas_have_no_
internal_fields` обходит все модели модуля и падает, если такое поле появится.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.schemas.common import AmountRub, Money, Revision, Schema
from app.schemas.enums import ApplicationStatus, ClientReasonCode, PurposeCode, TermsSource

PurposeText = Annotated[str, Field(max_length=2000)]
TermMonths = Annotated[int, Field(ge=1, le=120)]


class TermsField(StrEnum):
    PURPOSE_CODE = "purpose_code"
    REQUESTED_AMOUNT_RUB = "requested_amount_rub"
    TERM_MONTHS = "term_months"


class FieldSource(StrEnum):
    MANUAL = "MANUAL"
    RULES = "RULES"
    LLM = "LLM"


class CreditProduct(Schema):
    id: str
    name: str
    allowed_purposes: list[PurposeCode]
    min_amount_rub: Money
    max_amount_rub: Money
    min_term_months: int
    max_term_months: int
    annual_rate_pct: str = Field(examples=["24.00"])
    suitable: bool
    monthly_payment_rub: Money | None = Field(description="Только для подходящего продукта")
    unmet_constraints: list[str] = Field(examples=[["AMOUNT_ABOVE_PRODUCT_MAX"]])
    disclaimer: str = "Расчёт предварительный и не является решением банка"


class ApplicationCreate(Schema):
    purpose_text: PurposeText | None = None


class ApplicationPatch(Schema):
    """PATCH — единственный источник истины для черновика; все поля, кроме revision, опциональны."""

    revision: Revision
    purpose_text: PurposeText | None = None
    purpose_code: PurposeCode | None = None
    requested_amount_rub: AmountRub | None = None
    term_months: TermMonths | None = None
    product_id: str | None = Field(default=None, max_length=64)
    terms_field_sources: dict[TermsField, FieldSource] | None = None


class ClientOffer(Schema):
    """«Вы просили → Банк предлагает»: только условия, без DSCR и лимита."""

    amount_rub: Money
    term_months: int
    annual_rate_pct: str
    monthly_payment_rub: Money
    overpayment_rub: Money


class ClientInfoRequest(Schema):
    question_text: str
    answer_text: str | None
    answered_at: datetime | None


class TimelineEvent(Schema):
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    created_at: datetime


class ClientApplicationView(Schema):
    id: UUID
    revision: int  # нужен клиенту для PATCH/submit/offer/sign
    status: ApplicationStatus
    purpose_text: str | None
    purpose_code: PurposeCode | None
    requested_amount_rub: Money | None
    term_months: int | None
    product_id: str | None
    terms_source: TermsSource
    terms_field_sources: dict[TermsField, FieldSource]
    submitted_at: datetime | None
    client_reason_code: ClientReasonCode | None = Field(description="Причина отказа (шаблон)")
    offer: ClientOffer | None
    info_request: ClientInfoRequest | None
    timeline: list[TimelineEvent]


class InterpretStatus(StrEnum):
    OK = "OK"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNAVAILABLE = "UNAVAILABLE"


class InterpretRequest(Schema):
    purpose_text: PurposeText


class Suggestion(Schema):
    source: Literal[FieldSource.RULES, FieldSource.LLM]
    matched_text: str | None = None


class PurposeSuggestion(Suggestion):
    value: PurposeCode


class AmountSuggestion(Suggestion):
    value: Annotated[int, Field(strict=True, gt=0)]


class TermSuggestion(Suggestion):
    value: Annotated[int, Field(strict=True, ge=1, le=120)]


class InterpretSuggestions(Schema):
    """Отсутствующее или null-поле означает, что предложение для него не найдено."""

    purpose_code: PurposeSuggestion | None = None
    requested_amount_rub: AmountSuggestion | None = None
    term_months: TermSuggestion | None = None


class InterpretResponse(Schema):
    """Не меняет заявку: поля сохраняются только PATCH-ем после «Подтвердить»."""

    status: InterpretStatus
    suggestion: InterpretSuggestions
    clarification_question: str | None


class SubmitRequest(Schema):
    revision: Revision
    bki_consent_version: str = Field(min_length=1, max_length=64)


class InfoResponseRequest(Schema):
    revision: Revision
    answer_text: str = Field(min_length=1, max_length=2000)


class RevisionRequest(Schema):
    """Тело offer/accept, offer/decline, sign/challenge."""

    revision: Revision


class ScheduleItem(Schema):
    number: int
    due_date: date
    payment_rub: Money
    interest_rub: Money
    principal_rub: Money
    balance_after_rub: Money


class ContractView(Schema):
    number: str
    status: Literal["DRAFT", "SIGNED", "ISSUED"]
    amount_rub: Money
    term_months: int
    annual_rate_pct: str
    monthly_payment_rub: Money
    overpayment_rub: Money
    account_masked: str
    schedule: list[ScheduleItem]
    signed_at: datetime | None
    issued_at: datetime | None


class SignChallenge(Schema):
    challenge_id: UUID
    expires_at: datetime
    demo_code: str | None = Field(description="Только при DEMO_AUTH_ENABLED=true")


class SignRequest(Schema):
    revision: Revision
    challenge_id: UUID
    code: str = Field(pattern=r"^\d{6}$")
