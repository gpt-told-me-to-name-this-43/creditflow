"""DTO кабинета менеджера (design.md §3.5). Внутренние поля расчёта есть только здесь.

Расчётные поля nullable: при `calculation_status = SKIPPED` (C4 — короткая история)
DSCR, score и лимита нет, а карточка всё равно должна отдаваться.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, StringConstraints, model_validator

from app.schemas.client import ContractView, FieldSource, TermsField
from app.schemas.common import AmountRub, Dscr, Money, Revision, Schema
from app.schemas.enums import (
    AiReportStatus,
    ApplicationStatus,
    CalculationStatus,
    ClientReasonCode,
    FallbackReason,
    ManagerAction,
    PurposeCode,
    ReasonCode,
    RiskLevel,
    StopFactor,
    SuggestedAction,
    TermsSource,
)


class QueueItem(Schema):
    id: UUID
    company_name: str
    status: ApplicationStatus
    submitted_at: datetime | None
    requested_amount_rub: Money | None
    term_months: int | None
    suggested_action: SuggestedAction | None
    blocking_codes: list[StopFactor]


class RuleTraceItem(Schema):
    rule: Literal["R1", "R2", "R3", "R4", "R5"]
    matched: bool
    detail: str | None


class MonthlyFeature(Schema):
    month: date
    revenue_rub: Money
    opex_rub: Money
    debt_svc_rub: Money


class Scoring(Schema):
    id: UUID
    kind: Literal["SUBMISSION", "COUNTER_OFFER"]
    calculation_status: CalculationStatus
    engine_version: str
    inputs_hash: str
    monthly_payment_rub: Money | None
    dscr: Dscr | None
    score: int | None
    factor_points: dict[str, int] | None
    risk_level: RiskLevel | None
    reason_codes: list[ReasonCode]
    positive_codes: list[ReasonCode]
    limit_rub: Money | None
    cfads_monthly_rub: Money | None
    revenue_change_pct: str | None
    existing_debt_payments_rub: Money
    business_age_months: int
    monthly: list[MonthlyFeature]


class Proposal(Schema):
    policy_version: str
    blocking_codes: list[StopFactor]
    suggested_action: SuggestedAction
    rule_trace: list[RuleTraceItem]


class ExternalSource(Schema):
    provider: Literal["EGRUL", "EGRIP", "FNS", "BKI", "BANK"]
    fetched_at: datetime
    summary: dict[str, JsonValue] = Field(
        description="Сводка источника: вложенные JSON-объекты, списки, bool, int и null. "
        "Денежные значения передаются строками с двумя знаками."
    )


class ManagerApplicationView(Schema):
    id: UUID
    revision: Revision
    status: ApplicationStatus
    company_name: str
    company_inn: str
    purpose_text: str | None
    purpose_code: PurposeCode | None
    requested_amount_rub: Money | None
    term_months: int | None
    product_id: str | None
    terms_source: TermsSource
    terms_field_sources: dict[TermsField, FieldSource]
    submitted_at: datetime | None
    sources: list[ExternalSource]
    scoring: Scoring | None  # None — до Submit
    proposal: Proposal | None
    allowed_actions: list[ManagerAction]  # из policy.allowed_actions — одна функция с POST
    ai_report: AiReportView | None
    decisions: list[DecisionHistoryItem]
    offers: list[OfferHistoryItem]
    info_requests: list[InfoRequestHistoryItem]
    contract: ManagerContractView | None
    sign_challenges: list[SignChallengeHistoryItem]
    timeline: list[ManagerTimelineEvent]


NonEmptyComment = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]


class ApproveDecision(Schema):
    revision: Revision
    action: Literal[ManagerAction.APPROVE]
    comment: NonEmptyComment | None = Field(
        default=None,
        description="Обязателен при suggested_action != ELIGIBLE_FOR_MANAGER_REVIEW. "
        "Условие по сохранённой рекомендации проверяет сервис (#7).",
    )


class CounterOfferDecision(Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "anyOf": [
                {"required": ["amount_rub"], "properties": {"amount_rub": {"type": "integer"}}},
                {"required": ["term_months"], "properties": {"term_months": {"type": "integer"}}},
            ]
        }
    )

    revision: Revision
    action: Literal[ManagerAction.COUNTER_OFFER]
    comment: NonEmptyComment
    client_reason_code: ClientReasonCode
    amount_rub: AmountRub | None = None
    term_months: int | None = Field(default=None, ge=1, le=120)

    @model_validator(mode="after")
    def _has_terms(self) -> Self:
        if self.amount_rub is None and self.term_months is None:
            raise ValueError("COUNTER_OFFER требует amount_rub и/или term_months")
        return self


class RequestInfoDecision(Schema):
    revision: Revision
    action: Literal[ManagerAction.REQUEST_INFO]
    comment: NonEmptyComment | None = None
    question_text: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]


class RejectDecision(Schema):
    revision: Revision
    action: Literal[ManagerAction.REJECT]
    comment: NonEmptyComment
    client_reason_code: ClientReasonCode


DecisionRequest = Annotated[
    ApproveDecision | CounterOfferDecision | RequestInfoDecision | RejectDecision,
    Field(discriminator="action"),
]


class DecisionResponse(Schema):
    decision_id: UUID
    status: ApplicationStatus
    revision: Revision


class OfferPreviewRequest(Schema):
    amount_rub: AmountRub
    term_months: int = Field(ge=1, le=120)


class OfferViolation(StrEnum):
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    AMOUNT_OUT_OF_PRODUCT = "AMOUNT_OUT_OF_PRODUCT"
    TERM_OUT_OF_PRODUCT = "TERM_OUT_OF_PRODUCT"
    AMOUNT_ABOVE_LIMIT = "AMOUNT_ABOVE_LIMIT"
    OFFER_NOT_IMPROVED = "OFFER_NOT_IMPROVED"
    CALCULATION_SKIPPED = "CALCULATION_SKIPPED"


class CalculatedOfferPreview(Schema):
    """200 даже при valid=false: вычислимые метрики сохраняются, причины в violations.

    Ничего не пишет в БД. Проверки условий совпадают с COUNTER_OFFER в decisions (#7).
    """

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {"properties": {"valid": {"const": True}, "violations": {"maxItems": 0}}},
                {"properties": {"valid": {"const": False}, "violations": {"minItems": 1}}},
            ]
        }
    )

    calculation_status: Literal[CalculationStatus.OK]
    monthly_payment_rub: Money
    dscr: Dscr
    score: int
    risk_level: RiskLevel
    limit_for_term_rub: Money | None
    valid: bool
    violations: list[OfferViolation]

    @model_validator(mode="after")
    def _validity(self) -> Self:
        if self.valid != (not self.violations):
            raise ValueError("valid=true только при пустом violations")
        return self


class SkippedOfferPreview(Schema):
    """200, valid=false, все метрики null: данных недостаточно или условия невычислимы.

    Невалидная структура запроса — 422; невалидный бизнес-оффер — 200 с violations.
    При исходном SKIPPED violations содержит CALCULATION_SKIPPED.
    """

    calculation_status: Literal[CalculationStatus.SKIPPED]
    monthly_payment_rub: None
    dscr: None
    score: None
    risk_level: None
    limit_for_term_rub: None
    valid: Literal[False]
    violations: list[OfferViolation] = Field(min_length=1)


OfferPreviewResponse = Annotated[
    CalculatedOfferPreview | SkippedOfferPreview, Field(discriminator="calculation_status")
]


class AiFactor(Schema):
    code: ReasonCode
    text: str


class AiReportBody(Schema):
    summary: str = Field(max_length=600)
    risk_factors: list[AiFactor]
    positive_factors: list[AiFactor]
    manager_questions: list[str] = Field(max_length=3)


class AiReportView(Schema):
    id: UUID
    scoring_result_id: UUID
    status: AiReportStatus
    llm_mode: Literal["openai", "replay", "disabled"]
    model_id: str | None
    prompt_version: str
    report: AiReportBody | None  # None, пока PENDING
    fallback_reason: FallbackReason | None
    updated_at: datetime


class AiFeedbackRequest(Schema):
    ai_report_id: UUID
    verdict: Literal["UP", "DOWN"]
    comment: str | None = Field(default=None, max_length=1000)


class ManagerStats(Schema):
    applications_by_status: dict[ApplicationStatus, int]
    median_time_to_decision_seconds: int | None
    suggested_action_distribution: dict[SuggestedAction, int]
    decisions_matching_suggestion_share: str | None = Field(examples=["0.75"])
    ai_feedback_up_share: dict[str, str] = Field(description="Ключ: prompt_version|model|source")


class DecisionHistoryItem(Schema):
    id: UUID
    proposal_id: UUID
    manager_user_id: UUID
    action: ManagerAction
    client_reason_code: ClientReasonCode | None
    comment: str | None
    created_at: datetime


class OfferHistoryItem(Schema):
    id: UUID
    decision_id: UUID
    amount_rub: Money
    term_months: int
    product_id: str
    annual_rate_pct: str
    monthly_payment_rub: Money
    overpayment_rub: Money
    scoring: Scoring = Field(description="Собственный расчёт оффера kind=COUNTER_OFFER")
    status: Literal["OPEN", "ACCEPTED", "DECLINED"]
    created_at: datetime


class InfoRequestHistoryItem(Schema):
    id: UUID
    decision_id: UUID
    question_text: str
    answer_text: str | None
    answered_at: datetime | None
    created_at: datetime


class ManagerContractView(ContractView):
    id: UUID
    signed_by_user_id: UUID | None


class SignChallengeHistoryItem(Schema):
    """Аудит подписания без кода, его хеша и demo_code."""

    id: UUID
    created_at: datetime
    expires_at: datetime
    attempts: int = Field(ge=0, le=3)
    used_at: datetime | None


class ManagerTimelineEvent(Schema):
    id: UUID
    actor_user_id: UUID | None = Field(description="null — SYSTEM")
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus
    created_at: datetime


ManagerApplicationView.model_rebuild()
