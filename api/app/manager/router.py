"""Маршруты кабинета менеджера: очередь, карточка, решения, предпросмотр оффера, сводка (#7),
AI-заключение и оценка 👍/👎 (#8).

Заменяют стабы контракта v1 с теми же путями, моделями и ошибками.
"""

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response

from app.api.examples import example_from
from app.api.stubs import (
    AppSettings,
    _build_decisions,
    _build_get_ai_report,
    _build_manager_card,
    _build_offer_preview,
    _build_queue,
    _build_regenerate_ai_report,
    _build_stats,
)
from app.applications import ai_reports, repo
from app.applications.deps import DbSession, Idem, Manager, require_manager, session_factory
from app.core.errors import errors
from app.manager import service, views
from app.manager.stats import manager_stats
from app.manager.views import ai_report_view
from app.schemas.common import ErrorCode as E
from app.schemas.enums import ApplicationStatus
from app.schemas.manager import (
    AiFeedbackRequest,
    AiReportView,
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
    "/applications/{application_id}/ai-report", response_model=AiReportView, responses=errors()
)
@example_from(_build_get_ai_report)
async def get_ai_report(application_id: UUID, session: DbSession) -> AiReportView:
    """Ровно то состояние, что сохранено в БД: GET ничего не вычисляет и не запускает."""
    return ai_report_view(await ai_reports.get_report(session, application_id))


@router.post(
    "/applications/{application_id}/ai-report",
    response_model=AiReportView,
    status_code=202,
    responses={
        200: {
            "model": AiReportView,
            "description": "Существующий READY/FALLBACK или свежий PENDING",
        },
        **errors(),
    },
    description="Не меняет revision заявки. Сериализация по записи ai_reports; "
    "свежий PENDING возвращается без повторного запуска (200), в том числе при regenerate. "
    "READY/FALLBACK без regenerate — 200; иначе, включая зависший PENDING, — 202. "
    "При 202 опрашивать GET каждые 3 секунды. Новая генерация использует "
    "generation_id и updated_at (design §3.6).",
)
@example_from(_build_regenerate_ai_report)
async def regenerate_ai_report(
    application_id: UUID,
    session: DbSession,
    settings: AppSettings,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    regenerate: bool = False,
) -> AiReportView:
    result = await ai_reports.request_generation(
        session,
        application_id,
        regenerate=regenerate,
        llm_mode=settings.llm_mode,
        deadline_seconds=settings.llm_report_deadline_seconds,
    )
    if not result.started:
        response.status_code = 200
        return ai_report_view(result.report)
    assert result.report.generation_id is not None
    # после COMMIT (request_generation закрыл транзакцию), как у Submit
    background.add_task(
        ai_reports.generate,
        session_factory(request),
        request.app.state.llm,
        settings.llm_report_deadline_seconds,
        result.report.id,
        result.report.generation_id,
    )
    return ai_report_view(result.report)


@router.post(
    "/applications/{application_id}/ai-feedback",
    status_code=204,
    responses=errors(),
    description="Не требует и не меняет revision заявки. UPSERT по "
    "(ai_report_id, manager_user_id): повтор заменяет оценку. Не меняет статус, расчёт "
    "и allowed_actions. Оценить можно заключение этой заявки в READY или FALLBACK; "
    "PENDING — 422.",
)
async def ai_feedback(
    application_id: UUID, body: AiFeedbackRequest, manager: Manager, session: DbSession
) -> None:
    await ai_reports.upsert_feedback(
        session, application_id, manager.id, body.ai_report_id, body.verdict, body.comment
    )


@router.get(
    "/stats", response_model=ManagerStats, responses=errors(not_found=False, validation=False)
)
@example_from(_build_stats)
async def stats(session: DbSession) -> ManagerStats:
    return await manager_stats(session)
