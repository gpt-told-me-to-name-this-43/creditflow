"""Submit: `DRAFT` → `UNDER_REVIEW` (design.md §3.7, issue #7 «Submit»).

Шаги строго по порядку:
1. проверки (ключ идемпотентности уже взят зависимостью `Idem`);
2. согласие БКИ — отдельная короткая транзакция, не откатывается при сбое;
3. ext-sim — только в память, вне транзакции заявки; сбой → 503, в БД остаётся согласие;
4. `BEGIN` → `SELECT … FOR UPDATE` → повторная проверка статуса и `revision`;
5. сверка руководителя → признаки → оценка → рекомендация;
6. атомарная запись снимков, операций, расчёта, рекомендации, `ai_reports (PENDING)`,
   перехода и ответа идемпотентности → `COMMIT`;
7. после `COMMIT` — фоновая генерация заключения (вызывающий маршрут).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.applications import ai_reports, fsm, repo
from app.applications.catalog import CatalogProduct, unmet_constraints
from app.applications.scoring_store import ScoringInputs, add_proposal, add_scoring
from app.applications.views import client_view
from app.core.config import Settings
from app.core.errors import AppError
from app.core.idempotency import Idempotency
from app.core.security import CurrentUser
from app.db.models import (
    AccountTransaction,
    Application,
    Company,
    Consent,
    CreditProduct,
    ExternalSnapshot,
    User,
)
from app.extsim_client import ExtSimClient
from app.extsim_client.dto import EgrulCompany, StatementPeriod, SubmitData
from app.extsim_client.errors import ExtSimError
from app.onboarding.authority import applicant_of, is_authorized
from app.onboarding.consents import BKI_VERSION
from app.schemas.client import ClientApplicationView
from app.schemas.common import (
    ApplicationIncompleteDetails,
    ErrorCode,
    ProductNotEligibleDetails,
)
from app.schemas.enums import ApplicationStatus, PurposeCode
from app.schemas.enums import BkiSummaryStatus as Bki
from app.schemas.enums import RegistryStatus as Registry
from app.scoring.categorization import RuleSet, StatementTransaction, categorize
from app.scoring.features import build_features
from app.scoring.policy import evaluate, stop_factors
from app.scoring.risk import assess

_REQUIRED = ("purpose_code", "requested_amount_rub", "term_months", "product_id")
HISTORY_MONTHS = 24  # запрашиваем больше окна: h считается от первой операции вообще


@dataclass(frozen=True)
class SubmitResult:
    view: ClientApplicationView
    report_id: uuid.UUID
    generation_id: uuid.UUID


def statement_period(as_of: date) -> StatementPeriod:
    """С 1-го числа за 24 мес. до месяца `as_of` по последний день предыдущего месяца."""
    month_start = as_of.replace(day=1)
    index = month_start.year * 12 + month_start.month - 1 - HISTORY_MONTHS
    return StatementPeriod(
        from_=date(index // 12, index % 12 + 1, 1), to=month_start - timedelta(days=1)
    )


def _precheck(application: Application, revision: int, product: CatalogProduct | None) -> None:
    if application.status != ApplicationStatus.DRAFT:
        raise AppError(ErrorCode.INVALID_STATUS_TRANSITION, "Заявка уже отправлена")
    repo.ensure_revision(application, revision)
    missing = [f for f in _REQUIRED if getattr(application, f) is None]
    if missing:
        raise AppError(
            ErrorCode.APPLICATION_INCOMPLETE,
            "Заполнены не все обязательные поля",
            ApplicationIncompleteDetails(missing_fields=missing),
        )
    assert product is not None and application.purpose_code is not None
    unmet = unmet_constraints(
        product,
        PurposeCode(application.purpose_code),
        application.requested_amount_rub,
        application.term_months,
    )
    if unmet:
        raise AppError(
            ErrorCode.PRODUCT_NOT_ELIGIBLE,
            "Продукт не подходит для условий заявки",
            ProductNotEligibleDetails(product_id=product.id, unmet_constraints=unmet),
        )


async def _bki_consent(
    sessions: async_sessionmaker[AsyncSession],
    application_id: uuid.UUID,
    company_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Шаг 2: создать или переиспользовать согласие; отдельная транзакция, переживает сбой."""
    async with sessions() as session, session.begin():
        await session.execute(
            insert(Consent)
            .values(
                user_id=user_id,
                company_id=company_id,
                application_id=application_id,
                type="BKI_REQUEST",
                text_version=BKI_VERSION,
            )
            .on_conflict_do_nothing(index_elements=["application_id", "type", "text_version"])
        )
        consent_id = await session.scalar(
            select(Consent.id).where(
                Consent.application_id == application_id,
                Consent.type == "BKI_REQUEST",
                Consent.text_version == BKI_VERSION,
            )
        )
    assert consent_id is not None
    return consent_id


def _transactions(data: SubmitData) -> list[StatementTransaction]:
    return [
        StatementTransaction(
            external_id=t.external_id,
            booked_at=t.booked_at,
            direction=t.direction,
            amount_rub=t.amount_rub,
            counterparty_inn=t.counterparty.inn,
            counterparty_is_bank=t.counterparty.is_bank,
            purpose=t.purpose,
        )
        for t in data.statement.transactions
    ]


async def submit(
    session: AsyncSession,
    sessions: async_sessionmaker[AsyncSession],
    ext_sim: ExtSimClient,
    rules: RuleSet,
    settings: Settings,
    user: CurrentUser,
    application_id: uuid.UUID,
    revision: int,
    bki_consent_version: str,
    idem: Idempotency,
) -> SubmitResult:
    # 1. Проверки без блокировки: до внешних вызовов, чтобы не дёргать ext-sim зря.
    application = await repo.get_owned(session, application_id, user.id)
    product_row = (
        await session.get(CreditProduct, application.product_id) if application.product_id else None
    )
    product = CatalogProduct.from_row(product_row) if product_row else None
    _precheck(application, revision, product)
    assert product is not None
    if bki_consent_version != BKI_VERSION:
        raise AppError(
            ErrorCode.CONSENT_REQUIRED, "Подтвердите актуальное согласие на запрос в БКИ"
        )
    company = await session.get(Company, application.company_id)
    owner = await session.get(User, user.id)
    assert company is not None and owner is not None
    company_id, company_inn = company.id, company.inn
    person_inn, full_name = owner.person_inn, owner.full_name
    # Читающая транзакция не держится во время внешних вызовов; после rollback объекты
    # сессии истекают, поэтому дальше — только скопированные значения.
    await session.rollback()

    # 2. Согласие БКИ.
    consent_id = await _bki_consent(sessions, application_id, company_id, user.id)

    # 3. Внешние данные — только в память.
    try:
        data = await ext_sim.fetch_all_for_submit(
            company_inn, consent_id, statement_period(settings.app_as_of_date)
        )
    except ExtSimError as exc:
        raise AppError(
            ErrorCode.PROVIDER_UNAVAILABLE, "Внешний сервис недоступен, повторите позже"
        ) from exc
    director_inn, _ = applicant_of(data.registry)
    categorized = categorize(
        _transactions(data),
        rules,
        company_inn=company_inn,
        director_inn=director_inn,
    )

    async with session.begin():
        # 4. Блокировка и повторная проверка: заявка могла измениться за время вызовов.
        application = await repo.lock_owned(session, application_id, user.id)
        _precheck(application, revision, product)
        assert application.requested_amount_rub is not None and application.term_months is not None

        # 5. Расчёт.
        features = build_features(
            categorized,
            as_of=settings.app_as_of_date,
            registered_at=data.registry.registered_at,
            bki_monthly_payments_rub=data.bki.monthly_payments_total_rub,
        )
        bki = Bki(data.bki.summary_status.value)
        blocking = stop_factors(
            registry_status=Registry(data.registry.status.value),
            applicant_authorized=is_authorized(data.registry, person_inn, full_name),
            bankruptcy=data.fns.bankruptcy,
            active_account_blocks=data.fns.active_account_blocks,
            features=features,
        )
        amount, term = application.requested_amount_rub, application.term_months
        risk = (
            None
            if features.skip_reason
            else assess(product.risk, Decimal(amount), term, features, bki)
        )
        proposal = evaluate(blocking, bki, risk)

        # 6. Атомарная запись.
        provider = "EGRUL" if isinstance(data.registry, EgrulCompany) else "EGRIP"
        for name, payload in (
            (provider, data.registry),
            ("FNS", data.fns),
            ("BKI", data.bki),
            ("BANK", data.statement),
        ):
            session.add(
                ExternalSnapshot(
                    company_id=company_id,
                    provider=name,
                    response_json=payload.model_dump(mode="json", by_alias=True),
                )
            )
        if categorized:
            rows = [
                {
                    "company_id": company_id,
                    "external_id": ct.tx.external_id,
                    "booked_at": ct.tx.booked_at,
                    "direction": ct.tx.direction,
                    "amount_rub": ct.tx.amount_rub,
                    "counterparty_inn": ct.tx.counterparty_inn,
                    "counterparty_name": t.counterparty.name,
                    "is_bank": ct.tx.counterparty_is_bank,
                    "purpose_text": ct.tx.purpose,
                    "category": ct.category.value,
                    "rule_id": ct.rule_id,
                }
                for ct, t in zip(categorized, data.statement.transactions, strict=True)
            ]
            stmt = insert(AccountTransaction).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["company_id", "external_id"],
                    set_={"category": stmt.excluded.category, "rule_id": stmt.excluded.rule_id},
                )
            )
        inputs = ScoringInputs(
            product_id=product.id,
            annual_rate_pct=product.annual_rate_pct,
            amount_rub=amount,
            term_months=term,
            as_of_date=settings.app_as_of_date,
            features=features,
            bki_status=bki,
            blocking_codes=proposal.blocking_codes,
        )
        scoring = add_scoring(session, application.id, "SUBMISSION", inputs, risk)
        await session.flush()
        add_proposal(session, scoring, proposal)
        report = ai_reports.new_pending(session, application.id, scoring, settings.llm_mode)
        application.current_scoring_id = scoring.id
        application.submitted_at = datetime.now(UTC)
        fsm.transition(session, application, fsm.Action.SUBMIT, fsm.Actor.CLIENT, user.id)
        await session.flush()
        view = await client_view(session, application, settings.app_as_of_date)
        await idem.complete(session, 200, view.model_dump(mode="json"))
    assert report.generation_id is not None
    return SubmitResult(view, report.id, report.generation_id)
