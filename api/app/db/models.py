"""Модель данных (design.md §3.7, issue #6): 15 таблиц design + contracts, sign_challenges,
idempotency_keys.

Соглашения:
- общая `Base` из `app.core.db` — одна metadata с naming convention для Alembic и gen_er;
- PK — UUID через `gen_random_uuid()` на стороне БД (PostgreSQL ≥ 13, расширение не нужно);
- время — `timestamptz`, `now()` по умолчанию; деньги — NUMERIC(15,2), DSCR — NUMERIC без масштаба;
- перечисления — TEXT + CHECK (значения берутся из тех же StrEnum, что и API);
- все внешние ключи — ON DELETE RESTRICT: история заявок не удаляется каскадом;
- scoring_results, decision_proposals, credit_decisions, external_snapshots,
  application_events — insert-only (триггер в миграции 0001), пересчёт = новая запись.
"""

import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Sequence,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.schemas.enums import (
    AiReportStatus,
    ApplicationStatus,
    CalculationStatus,
    ClientReasonCode,
    FallbackReason,
    ManagerAction,
    PurposeCode,
    RiskLevel,
    SuggestedAction,
    TermsSource,
    TransactionCategory,
)

MONEY = Numeric(15, 2)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


def _fk(target: str, *, nullable: bool = False, **kw: Any) -> Mapped[Any]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete="RESTRICT", **kw), nullable=nullable
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


def _in(
    column: str, values: Iterable[str] | type[StrEnum], name: str | None = None
) -> CheckConstraint:
    """TEXT + CHECK. Имя ограничения → `ck_<table>_<name>` по naming convention."""
    items = [v.value if isinstance(v, StrEnum) else v for v in values]
    listed = ", ".join(f"'{v}'" for v in items)
    return CheckConstraint(f"{column} IN ({listed})", name=name or column)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        _in("role", ["CLIENT", "MANAGER"]),
        CheckConstraint("person_inn ~ '^[0-9]{12}$'", name="person_inn_format"),
    )

    id: Mapped[uuid.UUID] = _pk()
    role: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text, unique=True)  # логин демо-учётки
    password_hash: Mapped[str] = mapped_column(Text)  # argon2
    full_name: Mapped[str] = mapped_column(Text)
    person_inn: Mapped[str | None] = mapped_column(Text)  # у менеджеров нет
    company_id: Mapped[uuid.UUID | None] = _fk("companies.id", nullable=True)
    created_at: Mapped[datetime] = _created()


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (_in("legal_form", ["LLC", "IE"]),)

    id: Mapped[uuid.UUID] = _pk()
    inn: Mapped[str] = mapped_column(Text, unique=True)
    legal_form: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    okved_main: Mapped[str] = mapped_column(Text)
    registered_at: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        _in("type", ["PD_PROCESSING", "BKI_REQUEST"]),
        # повторный Submit переиспользует согласие БКИ (design §3.7, шаг 2);
        # для PD_PROCESSING application_id = NULL, а NULL в UNIQUE не конфликтуют
        UniqueConstraint("application_id", "type", "text_version", name="application_type_version"),
    )

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    company_id: Mapped[uuid.UUID] = _fk("companies.id")
    application_id: Mapped[uuid.UUID | None] = _fk("applications.id", nullable=True)
    type: Mapped[str] = mapped_column(Text)
    text_version: Mapped[str] = mapped_column(Text)
    granted_at: Mapped[datetime] = _created()


class ExternalSnapshot(Base):
    __tablename__ = "external_snapshots"
    __table_args__ = (_in("provider", ["EGRUL", "EGRIP", "FNS", "BKI", "BANK"]),)

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _fk("companies.id")
    provider: Mapped[str] = mapped_column(Text)
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = _created()


class AccountTransaction(Base):
    __tablename__ = "account_transactions"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "external_id", name="company_external_id"
        ),  # upsert при Submit
        Index("ix_account_transactions_company_booked", "company_id", "booked_at"),
        _in("direction", ["IN", "OUT"]),
        _in("category", TransactionCategory),
        CheckConstraint("amount_rub > 0", name="amount_positive"),
    )

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _fk("companies.id")
    external_id: Mapped[str] = mapped_column(Text)
    booked_at: Mapped[date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(Text)
    amount_rub: Mapped[Decimal] = mapped_column(MONEY)
    counterparty_inn: Mapped[str | None] = mapped_column(Text)
    counterparty_name: Mapped[str] = mapped_column(Text)
    is_bank: Mapped[bool] = mapped_column(Boolean)
    purpose_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str] = mapped_column(Text)


class CreditProduct(Base):
    __tablename__ = "credit_products"
    __table_args__ = (
        CheckConstraint(
            "min_amount_rub > 0 AND min_amount_rub <= max_amount_rub", name="amount_range"
        ),
        CheckConstraint(
            "min_term_months >= 1 AND min_term_months <= max_term_months", name="term_range"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # investment | working_capital
    name: Mapped[str] = mapped_column(Text)
    allowed_purposes: Mapped[list[str]] = mapped_column(ARRAY(Text))
    min_amount_rub: Mapped[Decimal] = mapped_column(MONEY)
    max_amount_rub: Mapped[Decimal] = mapped_column(MONEY)
    min_term_months: Mapped[int] = mapped_column(Integer)
    max_term_months: Mapped[int] = mapped_column(Integer)
    annual_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_status_submitted", "status", "submitted_at"),  # очередь менеджера
        Index("ix_applications_owner", "owner_user_id"),
        # один DRAFT на клиента (#7): POST /applications — INSERT … ON CONFLICT DO NOTHING
        Index(
            "uq_applications_one_draft",
            "owner_user_id",
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),
        ),
        _in("status", ApplicationStatus),
        _in("purpose_code", PurposeCode),
        _in("terms_source", TermsSource),
        CheckConstraint(
            "requested_amount_rub > 0 AND requested_amount_rub = trunc(requested_amount_rub)",
            name="amount_whole_rubles",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    company_id: Mapped[uuid.UUID] = _fk("companies.id")
    owner_user_id: Mapped[uuid.UUID] = _fk("users.id")
    status: Mapped[str] = mapped_column(Text, server_default=ApplicationStatus.DRAFT.value)
    revision: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    purpose_text: Mapped[str | None] = mapped_column(Text)
    purpose_code: Mapped[str | None] = mapped_column(Text)
    requested_amount_rub: Mapped[Decimal | None] = mapped_column(MONEY)
    term_months: Mapped[int | None] = mapped_column(Integer)
    product_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("credit_products.id", ondelete="RESTRICT")
    )
    terms_source: Mapped[str] = mapped_column(Text, server_default=TermsSource.MANUAL.value)
    terms_field_sources_json: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    # Циклическая связь с scoring_results → use_alter: FK добавляется после обеих таблиц.
    current_scoring_id: Mapped[uuid.UUID | None] = _fk(
        "scoring_results.id", nullable=True, use_alter=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class ScoringResult(Base):
    __tablename__ = "scoring_results"
    __table_args__ = (
        _in("kind", ["SUBMISSION", "COUNTER_OFFER"]),
        _in("calculation_status", CalculationStatus),
        _in("risk_level", RiskLevel),
        # при OK все метрики заполнены, при SKIPPED — пусты (C4)
        CheckConstraint(
            "(calculation_status = 'OK') = (dscr IS NOT NULL AND score IS NOT NULL"
            " AND monthly_payment_rub IS NOT NULL AND risk_level IS NOT NULL)",
            name="metrics_iff_ok",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = _fk("applications.id")
    kind: Mapped[str] = mapped_column(Text)
    inputs_json: Mapped[dict[str, Any]] = mapped_column(JSONB)  # признаки + помесячные ряды
    inputs_hash: Mapped[str] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(Text)
    calculation_status: Mapped[str] = mapped_column(Text)
    monthly_payment_rub: Mapped[Decimal | None] = mapped_column(MONEY)
    dscr: Mapped[Decimal | None] = mapped_column(
        Numeric
    )  # без масштаба: пороги — по точному значению
    score: Mapped[int | None] = mapped_column(Integer)
    factor_points_json: Mapped[dict[str, int] | None] = mapped_column(JSONB)
    risk_level: Mapped[str | None] = mapped_column(Text)
    reason_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    positive_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    limit_rub: Mapped[Decimal | None] = mapped_column(MONEY)
    created_at: Mapped[datetime] = _created()


class DecisionProposal(Base):
    __tablename__ = "decision_proposals"
    __table_args__ = (_in("suggested_action", SuggestedAction),)

    id: Mapped[uuid.UUID] = _pk()
    scoring_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scoring_results.id", ondelete="RESTRICT"),
        unique=True,  # 1:1
    )
    policy_version: Mapped[str] = mapped_column(Text)
    blocking_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    suggested_action: Mapped[str] = mapped_column(Text)
    rule_trace_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class CreditDecision(Base):
    __tablename__ = "credit_decisions"
    __table_args__ = (_in("action", ManagerAction), _in("client_reason_code", ClientReasonCode))

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = _fk("applications.id")
    proposal_id: Mapped[uuid.UUID] = _fk("decision_proposals.id")
    manager_user_id: Mapped[uuid.UUID] = _fk("users.id")
    action: Mapped[str] = mapped_column(Text)
    client_reason_code: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (_in("status", ["OPEN", "ACCEPTED", "DECLINED"]),)

    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = _fk("credit_decisions.id")
    amount_rub: Mapped[Decimal] = mapped_column(MONEY)
    term_months: Mapped[int] = mapped_column(Integer)
    product_id: Mapped[str] = mapped_column(
        Text, ForeignKey("credit_products.id", ondelete="RESTRICT")
    )
    annual_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    monthly_payment_rub: Mapped[Decimal] = mapped_column(MONEY)
    offer_scoring_id: Mapped[uuid.UUID] = _fk("scoring_results.id")
    status: Mapped[str] = mapped_column(Text, server_default="OPEN")
    created_at: Mapped[datetime] = _created()


class InfoRequest(Base):
    __tablename__ = "info_requests"
    __table_args__ = (
        CheckConstraint("char_length(question_text) <= 1000", name="question_len"),
        CheckConstraint("char_length(answer_text) <= 2000", name="answer_len"),
    )

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = _fk("applications.id")
    decision_id: Mapped[uuid.UUID] = _fk("credit_decisions.id")
    question_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str | None] = mapped_column(Text)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


# Номер договора CF-<год>-<6 цифр> (миграция 0004): параллельные APPROVE не столкнутся.
CONTRACT_NUMBER_SEQ = Sequence("contract_number_seq", metadata=Base.metadata)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (_in("status", ["DRAFT", "SIGNED", "ISSUED"]),)

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("applications.id", ondelete="RESTRICT"), unique=True
    )
    number: Mapped[str] = mapped_column(Text, unique=True)
    amount_rub: Mapped[Decimal] = mapped_column(MONEY)
    term_months: Mapped[int] = mapped_column(Integer)
    annual_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    monthly_payment_rub: Mapped[Decimal] = mapped_column(MONEY)
    schedule_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default="DRAFT")
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_by_user_id: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_masked: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class SignChallenge(Base):
    __tablename__ = "sign_challenges"
    __table_args__ = (CheckConstraint("attempts BETWEEN 0 AND 3", name="attempts_range"),)

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = _fk("applications.id")
    code_hash: Mapped[str] = mapped_column(Text)  # код хранится только хешем
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class IdempotencyKey(Base):
    """Схема — issue #5: PK (user_id, key), TTL 24 ч, IN_PROGRESS старше 60 с — брошенная."""

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "key"),
        _in("status", ["IN_PROGRESS", "COMPLETED"]),
    )

    user_id: Mapped[uuid.UUID] = _fk("users.id")
    key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    canonical_path: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class AiReport(Base):
    __tablename__ = "ai_reports"
    __table_args__ = (
        _in("status", AiReportStatus),
        _in("llm_mode", ["openai", "replay", "disabled"]),
        _in("fallback_reason", FallbackReason),
        # generation_id есть только у PENDING (design §3.6, условное обновление по нему)
        CheckConstraint(
            "(status = 'PENDING') = (generation_id IS NOT NULL)", name="generation_iff_pending"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    application_id: Mapped[uuid.UUID] = _fk("applications.id")
    scoring_result_id: Mapped[uuid.UUID] = _fk("scoring_results.id")
    status: Mapped[str] = mapped_column(Text)
    llm_mode: Mapped[str] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    context_hash: Mapped[str] = mapped_column(Text)
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    fallback_reason: Mapped[str | None] = mapped_column(Text)
    generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class AiFeedback(Base):
    __tablename__ = "ai_feedback"
    __table_args__ = (
        UniqueConstraint(
            "ai_report_id", "manager_user_id", name="report_manager"
        ),  # повтор заменяет
        _in("verdict", ["UP", "DOWN"]),
    )

    id: Mapped[uuid.UUID] = _pk()
    ai_report_id: Mapped[uuid.UUID] = _fk("ai_reports.id")
    manager_user_id: Mapped[uuid.UUID] = _fk("users.id")
    verdict: Mapped[str] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ApplicationEvent(Base):
    __tablename__ = "application_events"
    __table_args__ = (
        Index("ix_application_events_app_created", "application_id", "created_at"),
        _in("from_status", ApplicationStatus),
        _in("to_status", ApplicationStatus),
    )

    id: Mapped[uuid.UUID] = _pk()  # порядок таймлайна — по created_at (индекс выше)
    application_id: Mapped[uuid.UUID] = _fk("applications.id")
    actor_user_id: Mapped[uuid.UUID | None] = _fk("users.id", nullable=True)  # NULL — SYSTEM
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
