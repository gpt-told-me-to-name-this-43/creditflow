"""Маршруты кабинета менеджера (#7): очередь, карточка, решения, предпросмотр оффера, сводка.

Заменяют стабы контракта v1 с теми же путями, моделями и ошибками. AI-заключение
и оценка 👍/👎 — #8 (пока стабы).
"""

from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.examples import example_from
from app.api.stubs import (
    AppSettings,
    _build_decisions,
    _build_manager_card,
    _build_offer_preview,
    _build_queue,
    _build_stats,
)
from app.applications import repo
from app.applications.deps import DbSession, Idem, Manager, require_manager
from app.core.errors import errors
from app.manager import service, views
from app.manager.stats import manager_stats
from app.schemas.common import ErrorCode as E
from app.schemas.enums import ApplicationStatus
from app.schemas.manager import (
    DecisionRequest,
    DecisionResponse,
    ManagerApplicationView,
    ManagerStats,
    OfferPreviewRequest,
    OfferPreviewResponse,
    QueueItem,
)

router = APIRouter(prefix="/manager", tags=["manager"], dependencies=[Depends(require_manager)])

_IDEMPOTENT_409_422 = (
    E.REVISION_CONFLICT,
    E.INVALID_STATUS_TRANSITION,
    E.IDEMPOTENCY_IN_PROGRESS,
    E.IDEMPOTENCY_KEY_REUSED,
)


@router.get("/applications", response_model=list[QueueItem], responses=errors(not_found=False))
@example_from(_build_queue)
async def queue(session: DbSession, status: ApplicationStatus | None = None) -> list[QueueItem]:
    return await views.queue(session, status)


@router.get(
    "/applications/{application_id}", response_model=ManagerApplicationView, responses=errors()
)
@example_from(_build_manager_card)
async def manager_card(application_id: UUID, session: DbSession) -> ManagerApplicationView:
    return await views.manager_card(session, await repo.get_any(session, application_id))


@router.post(
    "/applications/{application_id}/decisions",
    response_model=DecisionResponse,
    status_code=201,
    responses=errors(*_IDEMPOTENT_409_422, E.ACTION_NOT_ALLOWED, E.AMOUNT_ABOVE_LIMIT),
)
@example_from(_build_decisions)
async def decisions(
    application_id: UUID,
    body: DecisionRequest,
    idem: Idem,
    manager: Manager,
    session: DbSession,
    settings: AppSettings,
) -> DecisionResponse:
    return await service.decide(
        session, manager, application_id, body, settings.app_as_of_date, idem
    )


@router.post(
    "/applications/{application_id}/offer-preview",
    response_model=OfferPreviewResponse,
    responses=errors(E.INVALID_STATUS_TRANSITION),
    description="Вне UNDER_REVIEW — 409 INVALID_STATUS_TRANSITION. "
    "Предпросмотр без записи в БД. 200 valid=false для бизнес-нарушений; "
    "вычислимые метрики возвращаются даже для невалидного оффера. При исходном SKIPPED "
    "или невычислимых условиях все метрики null, valid=false и violations непустой. "
    "Невалидная структура запроса — 422. Проверки продукта, лимита и изменения условий "
    "совпадают с COUNTER_OFFER в decisions.",
)
@example_from(_build_offer_preview)
async def offer_preview(
    application_id: UUID, body: OfferPreviewRequest, session: DbSession
) -> OfferPreviewResponse:
    return await service.offer_preview(session, application_id, body.amount_rub, body.term_months)


@router.get(
    "/stats", response_model=ManagerStats, responses=errors(not_found=False, validation=False)
)
@example_from(_build_stats)
async def stats(session: DbSession) -> ManagerStats:
    return await manager_stats(session)
