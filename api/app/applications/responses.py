"""Ответы клиента после решения менеджера: вопрос, оффер, подписание (design §3.3, §3.7).

Каждая операция — `SELECT … FOR UPDATE`, проверка статуса и `revision`, эффект, переход FSM
и ответ идемпотентности в одной транзакции.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.applications import fsm, repo
from app.applications.views import client_view
from app.contracts import service as contracts
from app.core.errors import AppError
from app.core.idempotency import Idempotency
from app.core.security import CurrentUser
from app.db.models import Application, CreditDecision, InfoRequest, Offer
from app.schemas.client import ClientApplicationView
from app.schemas.common import ErrorCode
from app.schemas.enums import ApplicationStatus


def _ensure(application: Application, status: ApplicationStatus, revision: int) -> None:
    if application.status != status:
        raise AppError(ErrorCode.INVALID_STATUS_TRANSITION, "Действие недоступно в этом статусе")
    repo.ensure_revision(application, revision)


async def _complete(
    session: AsyncSession, application: Application, as_of: date, idem: Idempotency
) -> ClientApplicationView:
    await session.flush()
    view = await client_view(session, application, as_of)
    await idem.complete(session, 200, view.model_dump(mode="json"))
    return view


async def answer_info(
    session: AsyncSession,
    user: CurrentUser,
    application_id: uuid.UUID,
    revision: int,
    answer_text: str,
    as_of: date,
    idem: Idempotency,
) -> ClientApplicationView:
    """NEED_INFO → UNDER_REVIEW без пересчёта: ответ не меняет данные расчёта."""
    async with session.begin():
        application = await repo.lock_owned(session, application_id, user.id)
        _ensure(application, ApplicationStatus.NEED_INFO, revision)
        question = await session.scalar(
            select(InfoRequest)
            .where(InfoRequest.application_id == application.id, InfoRequest.answer_text.is_(None))
            .order_by(InfoRequest.created_at.desc())
            .limit(1)
        )
        assert question is not None  # NEED_INFO создаётся только вместе с вопросом
        question.answer_text = answer_text
        question.answered_at = datetime.now(UTC)
        fsm.transition(session, application, fsm.Action.ANSWER_INFO, fsm.Actor.CLIENT, user.id)
        return await _complete(session, application, as_of, idem)


async def _open_offer(session: AsyncSession, application: Application) -> Offer:
    offer = await session.scalar(
        select(Offer)
        .join(CreditDecision, CreditDecision.id == Offer.decision_id)
        .where(CreditDecision.application_id == application.id, Offer.status == "OPEN")
        .order_by(Offer.created_at.desc())
        .limit(1)
        .with_for_update(of=Offer)
    )
    assert offer is not None  # COUNTER_OFFER создаётся только вместе с оффером
    return offer


async def accept_offer(
    session: AsyncSession,
    user: CurrentUser,
    application_id: uuid.UUID,
    revision: int,
    as_of: date,
    idem: Idempotency,
) -> ClientApplicationView:
    """Условия договора и текущий расчёт — из оффера; исходный запрос заявки сохраняется."""
    async with session.begin():
        application = await repo.lock_owned(session, application_id, user.id)
        _ensure(application, ApplicationStatus.COUNTER_OFFER, revision)
        offer = await _open_offer(session, application)
        offer.status = "ACCEPTED"
        application.current_scoring_id = offer.offer_scoring_id
        await contracts.create_contract(
            session, application, offer.amount_rub, offer.term_months, offer.annual_rate_pct, as_of
        )
        fsm.transition(session, application, fsm.Action.ACCEPT_OFFER, fsm.Actor.CLIENT, user.id)
        return await _complete(session, application, as_of, idem)


async def decline_offer(
    session: AsyncSession,
    user: CurrentUser,
    application_id: uuid.UUID,
    revision: int,
    as_of: date,
    idem: Idempotency,
) -> ClientApplicationView:
    async with session.begin():
        application = await repo.lock_owned(session, application_id, user.id)
        _ensure(application, ApplicationStatus.COUNTER_OFFER, revision)
        offer = await _open_offer(session, application)
        offer.status = "DECLINED"
        fsm.transition(session, application, fsm.Action.DECLINE_OFFER, fsm.Actor.CLIENT, user.id)
        return await _complete(session, application, as_of, idem)


async def sign(
    session: AsyncSession,
    user: CurrentUser,
    application_id: uuid.UUID,
    revision: int,
    challenge_id: uuid.UUID,
    code: str,
    secret: str,
    as_of: date,
    idem: Idempotency,
) -> ClientApplicationView:
    """APPROVED → SIGNED. Неуспешная попытка сохраняет счётчик и не меняет revision."""
    failure: AppError | None = None
    async with session.begin():
        application = await repo.lock_owned(session, application_id, user.id)
        _ensure(application, ApplicationStatus.APPROVED, revision)
        failure = await contracts.check_code(session, application, challenge_id, code, secret)
        if failure is None:
            await contracts.mark_signed(session, application, user.id)
            return await _complete(session, application, as_of, idem)
    raise failure  # после COMMIT: счётчик попыток сохранён, ключ идемпотентности освобождается
