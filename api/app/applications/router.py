"""Клиентские маршруты конвейера (#7): каталог, черновик, submit, ответы, договор, подпись.

Заменяют одноимённые стабы контракта v1: пути, модели, ошибки и описания прежние,
примеры OpenAPI строят те же builder-функции из `app.api.stubs`.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response

from app.api.examples import example_from
from app.api.stubs import (
    AppSettings,
    _build_contract,
    _build_create_application,
    _build_credit_products,
    _build_get_application,
    _build_info_response,
    _build_list_applications,
    _build_offer_accept,
    _build_offer_decline,
    _build_patch_application,
    _build_sign,
    _build_sign_challenge,
    _build_submit,
)
from app.applications import ai_reports, catalog, repo, responses, service
from app.applications.deps import (
    BoundClient,
    DbSession,
    Idem,
    require_client,
    session_factory,
)
from app.applications.submit import submit as run_submit
from app.applications.views import client_view
from app.contracts import service as contracts
from app.core.errors import AppError, errors
from app.core.ratelimit import limit_challenge_issue
from app.schemas.client import (
    ApplicationCreate,
    ApplicationPatch,
    ClientApplicationView,
    ContractView,
    CreditProduct,
    InfoResponseRequest,
    RevisionRequest,
    SignChallenge,
    SignRequest,
    SubmitRequest,
)
from app.schemas.common import ErrorCode as E
from app.schemas.enums import PurposeCode

router = APIRouter(tags=["client"], dependencies=[Depends(require_client)])


@router.get(
    "/credit-products",
    response_model=list[CreditProduct],
    responses=errors(not_found=False),
    description=(
        "Оба продукта каталога с подбором по design §3.3. Незаданный фильтр не проверяется; "
        "`monthly_payment_rub` — только для подходящего продукта при заданных amount и term. "
        "`unmet_constraints`: PURPOSE_NOT_ALLOWED, AMOUNT_BELOW_PRODUCT_MIN, "
        "AMOUNT_ABOVE_PRODUCT_MAX, TERM_BELOW_PRODUCT_MIN, TERM_ABOVE_PRODUCT_MAX. "
        "Пример ответа — для `?purpose=EQUIPMENT&amount=3000000&term=36` (C2)."
    ),
)
@example_from(_build_credit_products)
async def credit_products(
    session: DbSession,
    purpose: PurposeCode | None = None,
    amount: Annotated[int | None, Query(gt=0)] = None,
    term: Annotated[int | None, Query(ge=1, le=120)] = None,
) -> list[CreditProduct]:
    return catalog.match_products(await catalog.load_catalog(session), purpose, amount, term)


@router.post(
    "/applications",
    response_model=ClientApplicationView,
    status_code=201,
    responses={
        200: {
            "model": ClientApplicationView,
            "description": "Существующий DRAFT; тело не применяется",
        },
        **errors(E.COMPANY_NOT_BOUND, not_found=False),
    },
    description="201: новый DRAFT; 200: существующий, без применения тела. "
    "Изменение только PATCH. Один DRAFT на клиента, в том числе при параллельных запросах.",
)
@example_from(_build_create_application)
async def create_application(
    body: ApplicationCreate,
    response: Response,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
) -> ClientApplicationView:
    application, created = await service.create_draft(session, user, body)
    if not created:
        response.status_code = 200
    return await client_view(session, application, settings.app_as_of_date)


@router.get(
    "/applications",
    response_model=list[ClientApplicationView],
    responses=errors(E.COMPANY_NOT_BOUND, not_found=False, validation=False),
)
@example_from(_build_list_applications)
async def list_applications(
    user: BoundClient, session: DbSession, settings: AppSettings
) -> list[ClientApplicationView]:
    return [
        await client_view(session, application, settings.app_as_of_date)
        for application in await service.list_applications(session, user)
    ]


@router.get(
    "/applications/{application_id}",
    response_model=ClientApplicationView,
    responses=errors(
        E.COMPANY_NOT_BOUND,
    ),
)
@example_from(_build_get_application)
async def get_application(
    application_id: UUID, user: BoundClient, session: DbSession, settings: AppSettings
) -> ClientApplicationView:
    application = await repo.get_owned(session, application_id, user.id)
    return await client_view(session, application, settings.app_as_of_date)


@router.patch(
    "/applications/{application_id}",
    response_model=ClientApplicationView,
    responses=errors(E.COMPANY_NOT_BOUND, E.REVISION_CONFLICT, E.INVALID_STATUS_TRANSITION),
    description="Сохранение подтверждённых полей черновика, только DRAFT. "
    "Пропуск поля оставляет значение, null очищает. terms_source вычисляет сервер. "
    "Успех увеличивает revision; следующий запрос использует revision из ответа.",
)
@example_from(_build_patch_application)
async def patch_application(
    application_id: UUID,
    body: ApplicationPatch,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
) -> ClientApplicationView:
    application = await service.patch_draft(session, user, application_id, body)
    return await client_view(session, application, settings.app_as_of_date)


@router.post(
    "/applications/{application_id}/submit",
    response_model=ClientApplicationView,
    responses=errors(
        E.COMPANY_NOT_BOUND,
        E.REVISION_CONFLICT,
        E.INVALID_STATUS_TRANSITION,
        E.IDEMPOTENCY_IN_PROGRESS,
        E.CONSENT_REQUIRED,
        E.APPLICATION_INCOMPLETE,
        E.PRODUCT_NOT_ELIGIBLE,
        E.IDEMPOTENCY_KEY_REUSED,
        E.PROVIDER_UNAVAILABLE,
    ),
    description="DRAFT → UNDER_REVIEW. Только заполненная заявка с подходящим продуктом "
    "и актуальным bki_consent_version после явного согласия. Синхронный сбор источников "
    "и расчёт; AI-заключение в фоне. 503 PROVIDER_UNAVAILABLE сохраняет DRAFT: можно "
    "повторить тот же запрос с тем же Idempotency-Key.",
)
@example_from(_build_submit)
async def submit(
    application_id: UUID,
    body: SubmitRequest,
    idem: Idem,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
    request: Request,
    background: BackgroundTasks,
) -> ClientApplicationView:
    sessions = session_factory(request)
    result = await run_submit(
        session,
        sessions,
        request.app.state.ext_sim,
        request.app.state.categorization_rules,
        settings,
        user,
        application_id,
        body.revision,
        body.bki_consent_version,
        idem,
    )
    # шаг 7: после COMMIT; падение процесса здесь закрывает recover_stale_ai_reports()
    background.add_task(ai_reports.generate, sessions, result.report_id, result.generation_id)
    return result.view


_IDEMPOTENT_409_422 = (
    E.REVISION_CONFLICT,
    E.INVALID_STATUS_TRANSITION,
    E.IDEMPOTENCY_IN_PROGRESS,
    E.IDEMPOTENCY_KEY_REUSED,
)


@router.post(
    "/applications/{application_id}/info-response",
    response_model=ClientApplicationView,
    responses=errors(E.COMPANY_NOT_BOUND, *_IDEMPOTENT_409_422),
)
@example_from(_build_info_response)
async def info_response(
    application_id: UUID,
    body: InfoResponseRequest,
    idem: Idem,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
) -> ClientApplicationView:
    return await responses.answer_info(
        session,
        user,
        application_id,
        body.revision,
        body.answer_text,
        settings.app_as_of_date,
        idem,
    )


@router.post(
    "/applications/{application_id}/offer/accept",
    response_model=ClientApplicationView,
    responses=errors(E.COMPANY_NOT_BOUND, *_IDEMPOTENT_409_422),
)
@example_from(_build_offer_accept)
async def offer_accept(
    application_id: UUID,
    body: RevisionRequest,
    idem: Idem,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
) -> ClientApplicationView:
    return await responses.accept_offer(
        session, user, application_id, body.revision, settings.app_as_of_date, idem
    )


@router.post(
    "/applications/{application_id}/offer/decline",
    response_model=ClientApplicationView,
    responses=errors(E.COMPANY_NOT_BOUND, *_IDEMPOTENT_409_422),
)
@example_from(_build_offer_decline)
async def offer_decline(
    application_id: UUID,
    body: RevisionRequest,
    idem: Idem,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
) -> ClientApplicationView:
    return await responses.decline_offer(
        session, user, application_id, body.revision, settings.app_as_of_date, idem
    )


@router.get(
    "/applications/{application_id}/contract",
    response_model=ContractView,
    responses=errors(
        E.COMPANY_NOT_BOUND,
    ),
)
@example_from(_build_contract)
async def contract(application_id: UUID, user: BoundClient, session: DbSession) -> ContractView:
    await repo.get_owned(session, application_id, user.id)
    found = await contracts.get_contract(session, application_id)
    if found is None:  # договор появляется при переходе в APPROVED
        raise AppError(E.NOT_FOUND, "Договор ещё не сформирован")
    return contracts.contract_view(found)


@router.post(
    "/applications/{application_id}/sign/challenge",
    response_model=SignChallenge,
    response_model_exclude_none=True,
    responses=errors(
        E.COMPANY_NOT_BOUND,
        E.REVISION_CONFLICT,
        E.INVALID_STATUS_TRANSITION,
        E.TOO_MANY_ATTEMPTS,
        challenge=True,
    ),
    description="Только APPROVED; UI предварительно получает подтверждение ознакомления "
    "с договором. Выдаёт новый код на 5 минут и инвалидирует предыдущий; максимум 3 попытки. "
    "Не более 5 challenge на заявку за 15 минут: 429 scope CHALLENGE_ISSUE и Retry-After. "
    "Не требует Idempotency-Key. В sign передать revision из этого ответа. "
    "demo_code показывать только из ответа API; отсутствует при DEMO_AUTH_ENABLED=false.",
    dependencies=[Depends(limit_challenge_issue)],
)
@example_from(_build_sign_challenge)
async def sign_challenge(
    application_id: UUID,
    body: RevisionRequest,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
) -> SignChallenge:
    return await contracts.issue_challenge(
        session,
        user.id,
        application_id,
        body.revision,
        settings.app_secret_key,
        demo=settings.demo_auth_enabled,
    )


@router.post(
    "/applications/{application_id}/sign",
    response_model=ClientApplicationView,
    responses=errors(
        E.COMPANY_NOT_BOUND,
        *_IDEMPOTENT_409_422,
        E.SIGN_CODE_INVALID,
        E.SIGN_CHALLENGE_EXPIRED,
        E.TOO_MANY_ATTEMPTS,
        signing=True,
    ),
    description="APPROVED → SIGNED с актуальной revision из challenge. Неверный код — "
    "422 SIGN_CODE_INVALID с details.remaining_attempts; третья неверная попытка — "
    "429 scope SIGN_ATTEMPTS без Retry-After, challenge недействителен. "
    "Неизвестный, чужой, просроченный, использованный или заменённый challenge — "
    "422 SIGN_CHALLENGE_EXPIRED. "
    "Неуспешная попытка не меняет revision заявки. Успех запускает выдачу SYSTEM: "
    "SIGNED → ISSUED через 3–5 с; опрашивать карточку каждые 2 с. Повтор успешного "
    "запроса с тем же ключом возвращает сохранённый ответ.",
)
@example_from(_build_sign)
async def sign(
    application_id: UUID,
    body: SignRequest,
    idem: Idem,
    user: BoundClient,
    session: DbSession,
    settings: AppSettings,
    request: Request,
    background: BackgroundTasks,
) -> ClientApplicationView:
    view = await responses.sign(
        session,
        user,
        application_id,
        body.revision,
        body.challenge_id,
        body.code,
        settings.app_secret_key,
        settings.app_as_of_date,
        idem,
    )
    # после COMMIT: смоделированная выдача; при падении процесса — recover_pending_disbursements
    background.add_task(
        contracts.disburse_later,
        session_factory(request),
        application_id,
        request.app.state.disburse_delay,
    )
    return view
