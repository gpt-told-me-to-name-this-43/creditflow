"""ManagerService: решения по заявке и предпросмотр оффера (design.md §3.5, issue #7).

Решение — одна транзакция: `SELECT … FOR UPDATE`, статус `UNDER_REVIEW`, свежая `revision`,
`allowed_actions` из той же функции, что карточка, запись решения, переход FSM, ответ
идемпотентности. Два параллельных решения дают ровно одну запись `credit_decisions`.
"""

import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import fsm, repo
from app.applications.catalog import CatalogProduct
from app.applications.scoring_store import Current, add_scoring, load_current
from app.contracts.service import create_contract
from app.core.errors import AppError
from app.core.idempotency import Idempotency
from app.core.security import CurrentUser
from app.db.models import Application, CreditDecision, CreditProduct, InfoRequest, Offer
from app.manager.offers import check_offer, preview, raise_for_decision
from app.schemas.common import ErrorCode, ValidationDetail, ValidationDetails
from app.schemas.enums import ApplicationStatus, ManagerAction, SuggestedAction
from app.schemas.manager import (
    ApproveDecision,
    CounterOfferDecision,
    DecisionRequest,
    DecisionResponse,
    OfferPreviewResponse,
    RejectDecision,
    RequestInfoDecision,
)
from app.scoring.policy import allowed_actions

# Действие, совпадающее с рекомендацией; иначе комментарий обязателен.
MATCHING: dict[SuggestedAction, ManagerAction] = {
    SuggestedAction.ELIGIBLE_FOR_MANAGER_REVIEW: ManagerAction.APPROVE,
    SuggestedAction.COUNTER_OFFER_CANDIDATE: ManagerAction.COUNTER_OFFER,
    SuggestedAction.BLOCKED_BY_RULE: ManagerAction.REJECT,
    SuggestedAction.MANUAL_REVIEW: ManagerAction.REQUEST_INFO,
}

_ACTION = {
    ManagerAction.APPROVE: fsm.Action.APPROVE,
    ManagerAction.REJECT: fsm.Action.REJECT,
    ManagerAction.COUNTER_OFFER: fsm.Action.COUNTER_OFFER,
    ManagerAction.REQUEST_INFO: fsm.Action.REQUEST_INFO,
}


def manager_actions(current: Current) -> list[ManagerAction]:
    return list(allowed_actions(current.inputs.blocking_codes, current.scoring.limit_rub))


async def _product(session: AsyncSession, product_id: str) -> CatalogProduct:
    row = await session.get(CreditProduct, product_id)
    assert row is not None
    return CatalogProduct.from_row(row)


def _ensure_reviewable(application: Application) -> None:
    if application.status != ApplicationStatus.UNDER_REVIEW:
        raise AppError(
            ErrorCode.INVALID_STATUS_TRANSITION, "Заявка уже не на рассмотрении, обновите карточку"
        )


async def offer_preview(
    session: AsyncSession, application_id: uuid.UUID, amount_rub: int, term_months: int
) -> OfferPreviewResponse:
    """Ничего не пишет в БД: только чтение и чистые функции."""
    application = await repo.get_any(session, application_id)
    _ensure_reviewable(application)
    current = await load_current(session, application)
    assert current is not None
    product = await _product(session, current.inputs.product_id)
    return preview(
        check_offer(current.inputs, product, current.scoring.limit_rub, amount_rub, term_months)
    )


async def decide(
    session: AsyncSession,
    manager: CurrentUser,
    application_id: uuid.UUID,
    body: DecisionRequest,
    as_of: date,
    idem: Idempotency,
) -> DecisionResponse:
    async with session.begin():
        application = await repo.lock_any(session, application_id)
        _ensure_reviewable(application)
        repo.ensure_revision(application, body.revision)
        current = await load_current(session, application)
        assert current is not None
        if body.action not in manager_actions(current):
            raise AppError(ErrorCode.ACTION_NOT_ALLOWED, "Действие недоступно для этой заявки")
        suggested = SuggestedAction(current.proposal.suggested_action)
        if MATCHING[suggested] is not body.action and not body.comment:
            raise AppError(
                ErrorCode.VALIDATION_ERROR,
                "Действие расходится с рекомендацией: нужен комментарий",
                ValidationDetails(
                    fields=[
                        ValidationDetail(
                            field="body.comment",
                            code="COMMENT_REQUIRED",
                            message="Обоснуйте отклонение от рекомендации",
                        )
                    ]
                ),
            )

        decision = CreditDecision(
            id=uuid.uuid4(),
            application_id=application.id,
            proposal_id=current.proposal.id,
            manager_user_id=manager.id,
            action=body.action.value,
            client_reason_code=(
                body.client_reason_code.value
                if isinstance(body, RejectDecision | CounterOfferDecision)
                else None
            ),
            comment=body.comment,
        )
        session.add(decision)
        await session.flush()

        product = await _product(session, current.inputs.product_id)
        if isinstance(body, CounterOfferDecision):
            check = check_offer(
                current.inputs,
                product,
                current.scoring.limit_rub,
                body.amount_rub,
                body.term_months,
            )
            raise_for_decision(check)
            assert check.risk is not None
            scoring = add_scoring(
                session, application.id, "COUNTER_OFFER", check.inputs, check.risk
            )
            await session.flush()
            session.add(
                Offer(
                    decision_id=decision.id,
                    amount_rub=check.amount,
                    term_months=check.term,
                    product_id=product.id,
                    annual_rate_pct=product.annual_rate_pct,
                    monthly_payment_rub=check.risk.monthly_payment_rub,
                    offer_scoring_id=scoring.id,
                    status="OPEN",
                )
            )
        elif isinstance(body, RequestInfoDecision):
            session.add(
                InfoRequest(
                    application_id=application.id,
                    decision_id=decision.id,
                    question_text=body.question_text,
                )
            )
        elif isinstance(body, ApproveDecision):
            assert application.requested_amount_rub is not None
            assert application.term_months is not None
            await create_contract(
                session,
                application,
                application.requested_amount_rub,
                application.term_months,
                product.annual_rate_pct,
                as_of,
            )

        target = fsm.transition(
            session, application, _ACTION[body.action], fsm.Actor.MANAGER, manager.id
        )
        response = DecisionResponse(
            decision_id=decision.id, status=target, revision=application.revision
        )
        await idem.complete(session, 201, response.model_dump(mode="json"))
    return response
