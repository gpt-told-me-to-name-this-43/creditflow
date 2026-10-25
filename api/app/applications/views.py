"""Клиентская модель заявки (design.md §3.3): статус, условия, таймлайн, оффер, вопрос.

Строится только схемами `app.schemas.client`, где внутренних полей (score, DSCR, лимит,
коды, комментарий менеджера) нет физически. Деньги считаются чистыми функциями ядра.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import fsm
from app.applications.catalog import CatalogProduct, unmet_constraints
from app.db.models import Application, ApplicationEvent, CreditDecision, InfoRequest, Offer
from app.db.models import CreditProduct as CreditProductRow
from app.schemas.client import (
    ClientAction,
    ClientApplicationView,
    ClientInfoRequest,
    ClientOffer,
    FieldSource,
    TermsField,
    TimelineEvent,
)
from app.schemas.enums import (
    ApplicationStatus,
    ClientReasonCode,
    ManagerAction,
    PurposeCode,
    TermsSource,
)
from app.scoring.money import money_str
from app.scoring.risk import monthly_payment
from app.scoring.schedule import build_schedule

# Статусы, в которых клиент видит оффер: открытый, отклонённый или принятый.
_OFFER_VISIBLE = frozenset(
    {
        ApplicationStatus.COUNTER_OFFER,
        ApplicationStatus.DECLINED,
        ApplicationStatus.APPROVED,
        ApplicationStatus.SIGNED,
        ApplicationStatus.ISSUED,
    }
)


def _terms_money(
    product: CatalogProduct, amount: Decimal, term: int, issued_on: date
) -> tuple[str, str]:
    """Платёж и переплата по графику; вызывать только для условий в пределах продукта."""
    payment = money_str(monthly_payment(product.risk, amount, term))
    rows = build_schedule(amount, product.annual_rate_pct, term, issued_on)
    return payment, money_str(sum((r.interest_rub for r in rows), Decimal(0)))


def is_complete(application: Application, product: CatalogProduct | None) -> bool:
    if product is None or application.purpose_code is None:
        return False
    if application.requested_amount_rub is None or application.term_months is None:
        return False
    return not unmet_constraints(
        product,
        PurposeCode(application.purpose_code),
        application.requested_amount_rub,
        application.term_months,
    )


async def client_view(
    session: AsyncSession, application: Application, as_of_date: date
) -> ClientApplicationView:
    status = ApplicationStatus(application.status)
    product_row = (
        await session.get(CreditProductRow, application.product_id)
        if application.product_id
        else None
    )
    product = CatalogProduct.from_row(product_row) if product_row else None

    payment = overpayment = None
    amount, term = application.requested_amount_rub, application.term_months
    if (
        product is not None
        and amount is not None
        and term is not None
        and not unmet_constraints(product, None, amount, term)
    ):
        payment, overpayment = _terms_money(product, amount, term, as_of_date)

    actions = fsm.client_actions(status)
    if status is ApplicationStatus.DRAFT and not is_complete(application, product):
        actions.remove(ClientAction.SUBMIT)

    events = await session.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application.id)
        .order_by(ApplicationEvent.created_at, ApplicationEvent.id)
    )
    decision = await session.scalar(
        select(CreditDecision)
        .where(CreditDecision.application_id == application.id)
        .order_by(CreditDecision.created_at.desc())
        .limit(1)
    )
    reason = None
    if (
        status is ApplicationStatus.REJECTED
        and decision is not None
        and decision.action == ManagerAction.REJECT
        and decision.client_reason_code
    ):
        reason = ClientReasonCode(decision.client_reason_code)

    offer = None
    if status in _OFFER_VISIBLE:
        offer_row = await session.scalar(
            select(Offer)
            .join(CreditDecision, Offer.decision_id == CreditDecision.id)
            .where(CreditDecision.application_id == application.id)
            .order_by(Offer.created_at.desc())
            .limit(1)
        )
        offer_product = (
            CatalogProduct.from_row(row)
            if offer_row and (row := await session.get(CreditProductRow, offer_row.product_id))
            else None
        )
        if offer_row is not None and offer_product is not None:
            offer_payment, offer_overpayment = _terms_money(
                offer_product, offer_row.amount_rub, offer_row.term_months, as_of_date
            )
            offer = ClientOffer(
                amount_rub=money_str(offer_row.amount_rub),
                term_months=offer_row.term_months,
                annual_rate_pct=money_str(offer_row.annual_rate_pct),
                monthly_payment_rub=offer_payment,
                overpayment_rub=offer_overpayment,
            )
            if offer_row.status == "ACCEPTED":  # текущие условия — согласованные в оффере
                payment, overpayment = offer_payment, offer_overpayment

    info = await session.scalar(
        select(InfoRequest)
        .where(InfoRequest.application_id == application.id)
        .order_by(InfoRequest.created_at.desc())
        .limit(1)
    )

    return ClientApplicationView(
        id=application.id,
        revision=application.revision,
        status=status,
        purpose_text=application.purpose_text,
        purpose_code=PurposeCode(application.purpose_code) if application.purpose_code else None,
        requested_amount_rub=money_str(amount) if amount is not None else None,
        term_months=term,
        product_id=application.product_id,
        terms_source=TermsSource(application.terms_source),
        terms_field_sources={
            TermsField(field): FieldSource(source)
            for field, source in application.terms_field_sources_json.items()
        },
        allowed_actions=actions,
        annual_rate_pct=money_str(product.annual_rate_pct) if product else None,
        monthly_payment_rub=payment,
        overpayment_rub=overpayment,
        submitted_at=application.submitted_at,
        client_reason_code=reason,
        offer=offer,
        info_request=ClientInfoRequest(
            question_text=info.question_text,
            answer_text=info.answer_text,
            answered_at=info.answered_at,
        )
        if info
        else None,
        timeline=[
            TimelineEvent(
                from_status=ApplicationStatus(e.from_status) if e.from_status else None,
                to_status=ApplicationStatus(e.to_status),
                created_at=e.created_at,
            )
            for e in events
        ],
    )
