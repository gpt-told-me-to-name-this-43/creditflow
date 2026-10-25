"""Очередь и карточка менеджера (design.md §3.5): снимки, признаки, расчёт, история, действия.

`allowed_actions` и `offer_constraints` считаются той же функцией, что проверяет POST /decisions.
Внутренние поля расчёта есть только здесь — клиентская модель их не содержит.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications.catalog import CatalogProduct
from app.applications.scoring_store import ScoringInputs, load_current
from app.contracts.service import contract_view, get_contract
from app.db.models import (
    AiReport,
    Application,
    ApplicationEvent,
    Company,
    CreditDecision,
    CreditProduct,
    DecisionProposal,
    ExternalSnapshot,
    InfoRequest,
    Offer,
    ScoringResult,
    SignChallenge,
    User,
)
from app.manager.service import manager_actions
from app.schemas.client import FieldSource, TermsField
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
from app.schemas.manager import (
    AiReportBody,
    AiReportView,
    DecisionHistoryItem,
    ExternalSource,
    InfoRequestHistoryItem,
    ManagerApplicationView,
    ManagerContractView,
    ManagerTimelineEvent,
    MonthlyFeature,
    OfferConstraints,
    OfferHistoryItem,
    Proposal,
    QueueItem,
    RuleTraceItem,
    Scoring,
    SignChallengeHistoryItem,
)
from app.scoring.money import display_dscr, money_str
from app.scoring.schedule import build_schedule


def _money(value: Decimal | str | None) -> str | None:
    return None if value is None else money_str(Decimal(value))


def scoring_view(row: ScoringResult) -> Scoring:
    inputs = ScoringInputs.from_json(row.inputs_json)
    f = inputs.features
    return Scoring(
        id=row.id,
        kind=row.kind,
        calculation_status=CalculationStatus(row.calculation_status),
        engine_version=row.engine_version,
        inputs_hash=row.inputs_hash,
        monthly_payment_rub=_money(row.monthly_payment_rub),
        dscr=str(display_dscr(row.dscr)) if row.dscr is not None else None,
        score=row.score,
        factor_points=row.factor_points_json,
        risk_level=RiskLevel(row.risk_level) if row.risk_level else None,
        reason_codes=[ReasonCode(c) for c in row.reason_codes],
        positive_codes=[ReasonCode(c) for c in row.positive_codes],
        limit_rub=_money(row.limit_rub),
        cfads_monthly_rub=_money(f.cfads_monthly_rub),
        revenue_change_pct=_money(f.revenue_change_pct),
        existing_debt_payments_rub=money_str(f.existing_debt_payments_rub),
        business_age_months=f.business_age_months,
        account_history_months=f.h,
        monthly=[
            MonthlyFeature(
                month=p.month,
                revenue_rub=money_str(p.revenue),
                opex_rub=money_str(p.opex),
                debt_svc_rub=money_str(p.debt_svc),
            )
            for p in f.monthly
        ],
    )


def _source_summary(provider: str, data: dict[str, Any]) -> dict[str, Any]:
    if provider == "BANK":  # операции — в признаках и помесячном ряде, здесь только сводка
        return {
            "account_masked": data["account_masked"],
            "from": data["from"],
            "to": data["to"],
            "transactions_count": len(data["transactions"]),
        }
    return data


async def _sources(session: AsyncSession, application: Application) -> list[ExternalSource]:
    """Снимки Submit этой заявки: записаны в той же транзакции, что расчёт SUBMISSION
    (одинаковый `now()`), поэтому совпадают с ним по времени."""
    submitted = await session.scalar(
        select(ScoringResult.created_at)
        .where(ScoringResult.application_id == application.id, ScoringResult.kind == "SUBMISSION")
        .order_by(ScoringResult.created_at.desc())
        .limit(1)
    )
    if submitted is None:
        return []
    rows = await session.scalars(
        select(ExternalSnapshot)
        .where(
            ExternalSnapshot.company_id == application.company_id,
            ExternalSnapshot.fetched_at == submitted,
        )
        .order_by(ExternalSnapshot.provider)
    )
    return [
        ExternalSource(
            provider=r.provider,
            fetched_at=r.fetched_at,
            summary=_source_summary(r.provider, r.response_json),
        )
        for r in rows
    ]


def ai_report_view(row: AiReport) -> AiReportView:
    return AiReportView(
        id=row.id,
        scoring_result_id=row.scoring_result_id,
        status=AiReportStatus(row.status),
        llm_mode=row.llm_mode,
        model_id=row.model_id,
        prompt_version=row.prompt_version,
        report=AiReportBody.model_validate(row.report_json) if row.report_json else None,
        fallback_reason=FallbackReason(row.fallback_reason) if row.fallback_reason else None,
        updated_at=row.updated_at,
    )


async def manager_card(session: AsyncSession, application: Application) -> ManagerApplicationView:
    company = await session.get(Company, application.company_id)
    assert company is not None
    current = await load_current(session, application)
    under_review = application.status == ApplicationStatus.UNDER_REVIEW
    actions: list[ManagerAction] = manager_actions(current) if current and under_review else []
    constraints = None
    if ManagerAction.COUNTER_OFFER in actions:
        assert current is not None
        product_row = await session.get(CreditProduct, current.inputs.product_id)
        assert product_row is not None
        product = CatalogProduct.from_row(product_row)
        constraints = OfferConstraints(
            min_amount_rub=money_str(product.min_amount_rub),
            max_amount_rub=money_str(product.max_amount_rub),
            min_term_months=product.min_term_months,
            max_term_months=product.max_term_months,
        )

    names = {
        u.id: u.full_name
        for u in await session.scalars(
            select(User).where(
                User.id.in_(
                    select(ApplicationEvent.actor_user_id).where(
                        ApplicationEvent.application_id == application.id
                    )
                )
                | User.id.in_(
                    select(CreditDecision.manager_user_id).where(
                        CreditDecision.application_id == application.id
                    )
                )
            )
        )
    }
    decisions = list(
        await session.scalars(
            select(CreditDecision)
            .where(CreditDecision.application_id == application.id)
            .order_by(CreditDecision.created_at)
        )
    )
    offers = list(
        await session.scalars(
            select(Offer)
            .where(Offer.decision_id.in_([d.id for d in decisions]))
            .order_by(Offer.created_at)
        )
    )
    offer_items = []
    for o in offers:
        scoring = await session.get(ScoringResult, o.offer_scoring_id)
        assert scoring is not None
        as_of = ScoringInputs.from_json(scoring.inputs_json).as_of_date  # как у договора
        rows = build_schedule(o.amount_rub, o.annual_rate_pct, o.term_months, as_of)
        offer_items.append(
            OfferHistoryItem(
                id=o.id,
                decision_id=o.decision_id,
                amount_rub=money_str(o.amount_rub),
                term_months=o.term_months,
                product_id=o.product_id,
                annual_rate_pct=money_str(o.annual_rate_pct),
                monthly_payment_rub=money_str(o.monthly_payment_rub),
                overpayment_rub=money_str(sum((r.interest_rub for r in rows), Decimal(0))),
                scoring=scoring_view(scoring),
                status=o.status,
                created_at=o.created_at,
            )
        )
    infos = await session.scalars(
        select(InfoRequest)
        .where(InfoRequest.application_id == application.id)
        .order_by(InfoRequest.created_at)
    )
    report = await session.scalar(
        select(AiReport)
        .where(AiReport.application_id == application.id)
        .order_by(AiReport.created_at.desc())
        .limit(1)
    )
    contract = await get_contract(session, application.id)
    challenges = await session.scalars(
        select(SignChallenge)
        .where(SignChallenge.application_id == application.id)
        .order_by(SignChallenge.created_at)
    )
    events = await session.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application.id)
        .order_by(ApplicationEvent.created_at, ApplicationEvent.id)
    )
    proposal = current.proposal if current else None
    return ManagerApplicationView(
        id=application.id,
        revision=application.revision,
        status=ApplicationStatus(application.status),
        company_name=company.name,
        company_inn=company.inn,
        legal_form=company.legal_form,
        okved_main=company.okved_main,
        registered_at=company.registered_at,
        purpose_text=application.purpose_text,
        purpose_code=PurposeCode(application.purpose_code) if application.purpose_code else None,
        requested_amount_rub=_money(application.requested_amount_rub),
        term_months=application.term_months,
        product_id=application.product_id,
        terms_source=TermsSource(application.terms_source),
        terms_field_sources={
            TermsField(k): FieldSource(v) for k, v in application.terms_field_sources_json.items()
        },
        submitted_at=application.submitted_at,
        sources=await _sources(session, application),
        scoring=scoring_view(current.scoring) if current else None,
        proposal=_proposal(proposal) if proposal else None,
        allowed_actions=actions,
        offer_constraints=constraints,
        ai_report=ai_report_view(report) if report else None,
        decisions=[
            DecisionHistoryItem(
                id=d.id,
                proposal_id=d.proposal_id,
                manager_user_id=d.manager_user_id,
                manager_full_name=names.get(d.manager_user_id, ""),
                action=ManagerAction(d.action),
                client_reason_code=(
                    ClientReasonCode(d.client_reason_code) if d.client_reason_code else None
                ),
                comment=d.comment,
                created_at=d.created_at,
            )
            for d in decisions
        ],
        offers=offer_items,
        info_requests=[
            InfoRequestHistoryItem(
                id=i.id,
                decision_id=i.decision_id,
                question_text=i.question_text,
                answer_text=i.answer_text,
                answered_at=i.answered_at,
                created_at=i.created_at,
            )
            for i in infos
        ],
        contract=(
            ManagerContractView(
                **contract_view(contract).model_dump(),
                id=contract.id,
                signed_by_user_id=contract.signed_by_user_id,
            )
            if contract
            else None
        ),
        sign_challenges=[
            SignChallengeHistoryItem(
                id=c.id,
                created_at=c.created_at,
                expires_at=c.expires_at,
                attempts=c.attempts,
                used_at=c.used_at,
            )
            for c in challenges
        ],
        timeline=[
            ManagerTimelineEvent(
                id=e.id,
                actor_user_id=e.actor_user_id,
                actor_full_name=names.get(e.actor_user_id) if e.actor_user_id else None,
                from_status=ApplicationStatus(e.from_status) if e.from_status else None,
                to_status=ApplicationStatus(e.to_status),
                created_at=e.created_at,
            )
            for e in events
        ],
    )


def _proposal(row: DecisionProposal) -> Proposal:
    return Proposal(
        policy_version=row.policy_version,
        blocking_codes=[StopFactor(c) for c in row.blocking_codes],
        suggested_action=SuggestedAction(row.suggested_action),
        rule_trace=[RuleTraceItem.model_validate(t) for t in row.rule_trace_json],
    )


async def queue(session: AsyncSession, status: ApplicationStatus | None) -> list[QueueItem]:
    """Все поданные заявки (черновики менеджеру не видны), по `submitted_at`."""
    latest_proposal = (
        select(DecisionProposal.suggested_action, DecisionProposal.blocking_codes)
        .join(ScoringResult, ScoringResult.id == DecisionProposal.scoring_result_id)
        .where(ScoringResult.application_id == Application.id)
        .order_by(DecisionProposal.created_at.desc())
        .limit(1)
        .lateral()
    )
    query = (
        select(
            Application,
            Company,
            latest_proposal.c.suggested_action,
            latest_proposal.c.blocking_codes,
        )
        .join(Company, Company.id == Application.company_id)
        .outerjoin(latest_proposal, true())
        .where(Application.status != ApplicationStatus.DRAFT)
        .order_by(Application.submitted_at, Application.id)
    )
    if status is not None:
        query = query.where(Application.status == status)
    rows = (await session.execute(query)).all()
    return [
        QueueItem(
            id=a.id,
            company_name=c.name,
            company_inn=c.inn,
            product_id=a.product_id,
            status=ApplicationStatus(a.status),
            submitted_at=a.submitted_at,
            requested_amount_rub=_money(a.requested_amount_rub),
            term_months=a.term_months,
            suggested_action=SuggestedAction(action) if action else None,
            blocking_codes=[StopFactor(b) for b in blocking or []],
        )
        for a, c, action, blocking in rows
    ]
