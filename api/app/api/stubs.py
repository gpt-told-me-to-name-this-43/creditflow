"""Стабы контракта API v1 (issue #6, тег `contract-v1`).

Каждый эндпоинт из таблицы #6 объявлен с настоящими request/response-моделями
и описанием ошибок, а отвечает фиксированным примером, который проходит его
`response_model`. Фронт генерирует клиент из `docs/openapi.json` и работает на моках,
не дожидаясь бэка. Реализации заменяют стабы по модулям: auth/onboarding — #5,
заявки и решения — #7, AI — #8. Сигнатуры при этом не меняются (иначе — label
`contract-change` и запись в docs/api-changelog.md).

RBAC (`require_role` на уровне роутера) подключается в #5; матрица «роль × эндпоинт»
строится из `app.routes`, поэтому роутеры уже разделены по ролям.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from app.api.examples import attach_examples
from app.core.config import Settings
from app.core.errors import AppError, errors
from app.core.security import require_bearer
from app.schemas.auth import (
    Company,
    CompanyBindingRequest,
    ConsentText,
    ConsentType,
    DemoAccount,
    LoginRequest,
    Me,
    Role,
    TokenResponse,
)
from app.schemas.client import (
    AmountSuggestion,
    ApplicationCreate,
    ApplicationPatch,
    ClientApplicationView,
    ContractView,
    CreditProduct,
    FieldSource,
    InfoResponseRequest,
    InterpretRequest,
    InterpretResponse,
    InterpretStatus,
    InterpretSuggestions,
    RevisionRequest,
    ScheduleItem,
    SignChallenge,
    SignRequest,
    SubmitRequest,
    TermsField,
)
from app.schemas.common import ErrorCode as E
from app.schemas.enums import (
    AiReportStatus,
    ApplicationStatus,
    CalculationStatus,
    ManagerAction,
    PurposeCode,
    ReasonCode,
    RiskLevel,
    SuggestedAction,
    TermsSource,
)
from app.schemas.manager import (
    AiFeedbackRequest,
    AiReportView,
    CalculatedOfferPreview,
    DecisionRequest,
    DecisionResponse,
    ExternalSource,
    ManagerApplicationView,
    ManagerStats,
    MonthlyFeature,
    OfferPreviewRequest,
    OfferPreviewResponse,
    Proposal,
    QueueItem,
    RuleTraceItem,
    Scoring,
)
from app.scoring.money import money_str
from app.scoring.schedule import build_schedule

IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=128, description="UUID запроса")
]

_ID = UUID("7f3e2a10-0000-4000-8000-000000000001")
_NOW = datetime(2026, 10, 21, 9, 0, tzinfo=UTC)  # фиксированное время: OpenAPI-примеры стабильны

auth_router = APIRouter(prefix="/auth", tags=["auth"])
public_router = APIRouter(tags=["onboarding"])
onboarding_router = APIRouter(tags=["onboarding"], dependencies=[Depends(require_bearer)])
client_router = APIRouter(tags=["client"], dependencies=[Depends(require_bearer)])
manager_router = APIRouter(
    prefix="/manager", tags=["manager"], dependencies=[Depends(require_bearer)]
)


def app_settings(request: Request) -> Settings:
    return request.app.state.settings


AppSettings = Annotated[Settings, Depends(app_settings)]


def _client_app(status: ApplicationStatus = ApplicationStatus.DRAFT) -> ClientApplicationView:
    return ClientApplicationView(
        id=_ID,
        revision=1,
        status=status,
        purpose_text="Купить печь за 3 млн на 3 года",
        purpose_code=PurposeCode.EQUIPMENT,
        requested_amount_rub="3000000.00",
        term_months=36,
        product_id="investment",
        terms_source=TermsSource.RULES_CONFIRMED,
        terms_field_sources={
            TermsField.PURPOSE_CODE: FieldSource.RULES,
            TermsField.REQUESTED_AMOUNT_RUB: FieldSource.RULES,
            TermsField.TERM_MONTHS: FieldSource.MANUAL,
        },
        submitted_at=None,
        client_reason_code=None,
        offer=None,
        info_request=None,
        timeline=[],
    )


# --- Auth (#5) -------------------------------------------------------------------------


@auth_router.post(
    "/login",
    response_model=TokenResponse,
    responses=errors(E.INVALID_CREDENTIALS, E.TOO_MANY_ATTEMPTS, public=True),
)
async def login(body: LoginRequest) -> TokenResponse:
    return TokenResponse(access_token="stub.jwt.token", expires_in=8 * 3600)


@auth_router.get(
    "/me", response_model=Me, responses=errors(), dependencies=[Depends(require_bearer)]
)
async def me() -> Me:
    return Me(id=_ID, role=Role.CLIENT, full_name="Кузнецова Анна Михайловна", company_id=None)


@auth_router.get(
    "/demo-accounts",
    response_model=list[DemoAccount],
    responses=errors(public=True),
    description="Публичный маршрут. При DEMO_AUTH_ENABLED=false возвращает 404.",
)
async def demo_accounts(settings: AppSettings) -> list[DemoAccount]:
    if not settings.demo_auth_enabled:
        raise AppError(E.NOT_FOUND, "Not Found")
    return [
        DemoAccount(
            login="director.bakery@creditflow.demo",
            role=Role.CLIENT,
            label="Директор «Пекарни Плюс»",
            scenario="C2: оффер",
        )
    ]


# --- Онбординг (#5) --------------------------------------------------------------------


@public_router.get(
    "/consents/texts", response_model=list[ConsentText], responses=errors(public=True)
)
async def consent_texts() -> list[ConsentText]:
    return [
        ConsentText(type=ConsentType.PD_PROCESSING, version="pd-v1", text="…"),
        ConsentText(type=ConsentType.BKI_REQUEST, version="bki-v1", text="…"),
    ]


@onboarding_router.post(
    "/onboarding/company-binding",
    response_model=Company,
    responses=errors(
        E.INVALID_INN,
        E.CONSENT_REQUIRED,
        E.COMPANY_NOT_IN_REGISTRY,
        E.APPLICANT_NOT_AUTHORIZED,
        E.COMPANY_ALREADY_BOUND,
        E.USER_ALREADY_BOUND,
        E.PROVIDER_UNAVAILABLE,
    ),
)
async def company_binding(body: CompanyBindingRequest) -> Company:
    return Company(
        id=_ID,
        inn=body.inn,
        legal_form="LLC",
        name="ООО «Пекарня Плюс»",
        okved_main="10.71",
        registered_at=date(2023, 10, 21),
        bound_at=_NOW,
    )


@onboarding_router.get("/company", response_model=Company, responses=errors())
async def company() -> Company:
    return Company(
        id=_ID,
        inn="0099020010",
        legal_form="LLC",
        name="ООО «Пекарня Плюс»",
        okved_main="10.71",
        registered_at=date(2023, 10, 21),
        bound_at=_NOW,
    )


# --- Клиент (#7, #9) -------------------------------------------------------------------


@client_router.get("/credit-products", response_model=list[CreditProduct], responses=errors())
async def credit_products(
    purpose: PurposeCode | None = None,
    amount: Annotated[int | None, Query(gt=0)] = None,
    term: Annotated[int | None, Query(ge=1, le=120)] = None,
) -> list[CreditProduct]:
    return [
        CreditProduct(
            id="investment",
            name="Инвестиционный кредит",
            allowed_purposes=[
                PurposeCode.EQUIPMENT,
                PurposeCode.RENOVATION,
                PurposeCode.BUSINESS_EXPANSION,
            ],
            min_amount_rub="100000.00",
            max_amount_rub="5000000.00",
            min_term_months=12,
            max_term_months=60,
            annual_rate_pct="24.00",
            suitable=True,
            monthly_payment_rub="117698.56",
            unmet_constraints=[],
        )
    ]


@client_router.post(
    "/applications", response_model=ClientApplicationView, status_code=201, responses=errors()
)
async def create_application(body: ApplicationCreate) -> ClientApplicationView:
    return _client_app()


@client_router.get("/applications", response_model=list[ClientApplicationView], responses=errors())
async def list_applications() -> list[ClientApplicationView]:
    return [_client_app()]


@client_router.get(
    "/applications/{application_id}", response_model=ClientApplicationView, responses=errors()
)
async def get_application(application_id: UUID) -> ClientApplicationView:
    return _client_app()


@client_router.patch(
    "/applications/{application_id}",
    response_model=ClientApplicationView,
    responses=errors(E.REVISION_CONFLICT, E.INVALID_STATUS_TRANSITION),
)
async def patch_application(application_id: UUID, body: ApplicationPatch) -> ClientApplicationView:
    return _client_app()


@client_router.post(
    "/applications/{application_id}/interpret",
    response_model=InterpretResponse,
    responses=errors(E.INVALID_STATUS_TRANSITION),
)
async def interpret(application_id: UUID, body: InterpretRequest) -> InterpretResponse:
    return InterpretResponse(
        status=InterpretStatus.OK,
        suggestion=InterpretSuggestions(
            requested_amount_rub=AmountSuggestion(
                value=3_000_000, source=FieldSource.RULES, matched_text="3 млн"
            )
        ),
        clarification_question=None,
    )


@client_router.post(
    "/applications/{application_id}/submit",
    response_model=ClientApplicationView,
    responses=errors(
        E.REVISION_CONFLICT,
        E.INVALID_STATUS_TRANSITION,
        E.IDEMPOTENCY_IN_PROGRESS,
        E.CONSENT_REQUIRED,
        E.IDEMPOTENCY_KEY_REUSED,
        E.PROVIDER_UNAVAILABLE,
    ),
)
async def submit(
    application_id: UUID, body: SubmitRequest, idempotency_key: IdempotencyKey
) -> ClientApplicationView:
    return _client_app(ApplicationStatus.UNDER_REVIEW)


_IDEMPOTENT_409_422 = (
    E.REVISION_CONFLICT,
    E.INVALID_STATUS_TRANSITION,
    E.IDEMPOTENCY_IN_PROGRESS,
    E.IDEMPOTENCY_KEY_REUSED,
)


@client_router.post(
    "/applications/{application_id}/info-response",
    response_model=ClientApplicationView,
    responses=errors(*_IDEMPOTENT_409_422),
)
async def info_response(
    application_id: UUID, body: InfoResponseRequest, idempotency_key: IdempotencyKey
) -> ClientApplicationView:
    return _client_app(ApplicationStatus.UNDER_REVIEW)


@client_router.post(
    "/applications/{application_id}/offer/accept",
    response_model=ClientApplicationView,
    responses=errors(*_IDEMPOTENT_409_422),
)
async def offer_accept(
    application_id: UUID, body: RevisionRequest, idempotency_key: IdempotencyKey
) -> ClientApplicationView:
    return _client_app(ApplicationStatus.APPROVED)


@client_router.post(
    "/applications/{application_id}/offer/decline",
    response_model=ClientApplicationView,
    responses=errors(*_IDEMPOTENT_409_422),
)
async def offer_decline(
    application_id: UUID, body: RevisionRequest, idempotency_key: IdempotencyKey
) -> ClientApplicationView:
    return _client_app(ApplicationStatus.DECLINED)


@client_router.get(
    "/applications/{application_id}/contract", response_model=ContractView, responses=errors()
)
async def contract(application_id: UUID) -> ContractView:
    rows = build_schedule(Decimal("2340000"), Decimal("24"), 36, _NOW.date())
    return ContractView(
        number="CF-2026-000001",
        status="DRAFT",
        amount_rub="2340000.00",
        term_months=36,
        annual_rate_pct="24.00",
        monthly_payment_rub=money_str(rows[0].payment_rub),
        overpayment_rub=money_str(sum((r.interest_rub for r in rows), Decimal(0))),
        account_masked="40702 •••• 0010",
        schedule=[
            ScheduleItem(
                number=r.number,
                due_date=r.due_date,
                payment_rub=money_str(r.payment_rub),
                interest_rub=money_str(r.interest_rub),
                principal_rub=money_str(r.principal_rub),
                balance_after_rub=money_str(r.balance_after_rub),
            )
            for r in rows
        ],
        signed_at=None,
        issued_at=None,
    )


@client_router.post(
    "/applications/{application_id}/sign/challenge",
    response_model=SignChallenge,
    responses=errors(E.REVISION_CONFLICT, E.INVALID_STATUS_TRANSITION, E.TOO_MANY_ATTEMPTS),
)
async def sign_challenge(
    application_id: UUID, body: RevisionRequest, settings: AppSettings
) -> SignChallenge:
    return SignChallenge(
        challenge_id=_ID,
        expires_at=_NOW + timedelta(minutes=5),
        demo_code="123456" if settings.demo_auth_enabled else None,
    )


@client_router.post(
    "/applications/{application_id}/sign",
    response_model=ClientApplicationView,
    responses=errors(*_IDEMPOTENT_409_422, E.SIGN_CODE_INVALID, E.TOO_MANY_ATTEMPTS),
)
async def sign(
    application_id: UUID, body: SignRequest, idempotency_key: IdempotencyKey
) -> ClientApplicationView:
    return _client_app(ApplicationStatus.SIGNED)


# --- Менеджер (#7, #8, #10) ------------------------------------------------------------


@manager_router.get("/applications", response_model=list[QueueItem], responses=errors())
async def queue(status: ApplicationStatus | None = None) -> list[QueueItem]:
    return [
        QueueItem(
            id=_ID,
            company_name="ООО «Пекарня Плюс»",
            status=ApplicationStatus.UNDER_REVIEW,
            submitted_at=_NOW,
            requested_amount_rub="3000000.00",
            term_months=36,
            suggested_action=SuggestedAction.COUNTER_OFFER_CANDIDATE,
            blocking_codes=[],
        )
    ]


@manager_router.get(
    "/applications/{application_id}", response_model=ManagerApplicationView, responses=errors()
)
async def manager_card(application_id: UUID) -> ManagerApplicationView:
    # Пример C2 (M1): значения — эталон из design §3.4, а не произвольные числа.
    scoring = Scoring(
        id=_ID,
        kind="SUBMISSION",
        calculation_status=CalculationStatus.OK,
        engine_version="risk-1.0.0",
        inputs_hash="0" * 64,
        monthly_payment_rub="117698.56",
        dscr="1.10",
        score=63,
        factor_points={"dscr": 10, "bki": 30, "revenue": 8, "age": 15},
        risk_level=RiskLevel.MODERATE,
        reason_codes=[ReasonCode.DSCR_BELOW_TARGET, ReasonCode.REVENUE_DECLINE],
        positive_codes=[ReasonCode.CLEAN_CREDIT_HISTORY, ReasonCode.ESTABLISHED_BUSINESS],
        limit_rub="2340000.00",
        cfads_monthly_rub="240000.00",
        revenue_change_pct="-8.00",
        existing_debt_payments_rub="100000.00",
        business_age_months=36,
        monthly=[
            MonthlyFeature(
                month=date(y, m, 1),
                revenue_rub="1000000.00",
                opex_rub="760000.00",
                debt_svc_rub="100000.00",
            )
            for y, m in ((2025, 10), (2025, 11), (2025, 12), (2026, 1), (2026, 2), (2026, 3))
        ]
        + [
            MonthlyFeature(
                month=date(2026, m, 1),
                revenue_rub="920000.00",
                opex_rub=money_str(Decimal(920000 - net)),
                debt_svc_rub="100000.00",
            )
            for m, net in zip(
                range(4, 10), (230000, 235000, 238000, 242000, 245000, 250000), strict=True
            )
        ],
    )
    trace = [
        RuleTraceItem(rule=r, matched=r == "R3", detail=None)
        for r in ("R1", "R2", "R3", "R4", "R5")
    ]
    return ManagerApplicationView(
        id=application_id,
        revision=2,
        status=ApplicationStatus.UNDER_REVIEW,
        company_name="ООО «Пекарня Плюс»",
        company_inn="0099020010",
        purpose_text="Купить печь за 3 млн на 3 года",
        purpose_code=PurposeCode.EQUIPMENT,
        requested_amount_rub="3000000.00",
        term_months=36,
        product_id="investment",
        terms_source=TermsSource.RULES_CONFIRMED,
        terms_field_sources={TermsField.PURPOSE_CODE: FieldSource.RULES},
        submitted_at=_NOW,
        sources=[
            ExternalSource(
                provider="EGRUL",
                fetched_at=_NOW,
                summary={
                    "status": "ACTIVE",
                    "director": {"full_name": "Кузнецова Анна Михайловна", "inn": "009902001009"},
                },
            ),
            ExternalSource(
                provider="FNS",
                fetched_at=_NOW,
                summary={"bankruptcy": False, "active_account_blocks": 0},
            ),
            ExternalSource(
                provider="BKI",
                fetched_at=_NOW,
                summary={
                    "summary_status": "CLEAN",
                    "monthly_payments_total_rub": "100000.00",
                    "obligations": [
                        {
                            "creditor_name": "АО «Демо-Банк»",
                            "monthly_payment_rub": "100000.00",
                            "outstanding_rub": "2400000.00",
                        }
                    ],
                },
            ),
        ],
        scoring=scoring,
        proposal=Proposal(
            policy_version="policy-1.0.0",
            blocking_codes=[],
            suggested_action=SuggestedAction.COUNTER_OFFER_CANDIDATE,
            rule_trace=trace,
        ),
        # тот же результат, что policy.allowed_actions([], limit=2 340 000)
        allowed_actions=[
            ManagerAction.APPROVE,
            ManagerAction.COUNTER_OFFER,
            ManagerAction.REQUEST_INFO,
            ManagerAction.REJECT,
        ],
        ai_report=_ai_report(),
        decisions=[],
        offers=[],
        info_requests=[],
        contract=None,
        sign_challenges=[],
        timeline=[],
    )


@manager_router.post(
    "/applications/{application_id}/decisions",
    response_model=DecisionResponse,
    status_code=201,
    responses=errors(*_IDEMPOTENT_409_422, E.ACTION_NOT_ALLOWED, E.AMOUNT_ABOVE_LIMIT),
)
async def decisions(
    application_id: UUID, body: DecisionRequest, idempotency_key: IdempotencyKey
) -> DecisionResponse:
    statuses = {
        ManagerAction.APPROVE: ApplicationStatus.APPROVED,
        ManagerAction.COUNTER_OFFER: ApplicationStatus.COUNTER_OFFER,
        ManagerAction.REQUEST_INFO: ApplicationStatus.NEED_INFO,
        ManagerAction.REJECT: ApplicationStatus.REJECTED,
    }
    return DecisionResponse(
        decision_id=_ID, status=statuses[body.action], revision=body.revision + 1
    )


@manager_router.post(
    "/applications/{application_id}/offer-preview",
    response_model=OfferPreviewResponse,
    responses=errors(E.INVALID_STATUS_TRANSITION),
    description="Предпросмотр без записи в БД. 200 valid=false для бизнес-нарушений; "
    "вычислимые метрики возвращаются даже для невалидного оффера. При исходном SKIPPED "
    "или невычислимых условиях все метрики null, valid=false и violations непустой. "
    "Невалидная структура запроса — 422. Проверки продукта, лимита и изменения условий "
    "совпадают с COUNTER_OFFER в decisions; реализация — #7. Стаб возвращает пример C2.",
)
async def offer_preview(application_id: UUID, body: OfferPreviewRequest) -> OfferPreviewResponse:
    return CalculatedOfferPreview(
        calculation_status=CalculationStatus.OK,
        monthly_payment_rub="91804.88",
        dscr="1.25",
        score=83,
        risk_level=RiskLevel.LOW,
        limit_for_term_rub="2340000.00",
        valid=True,
        violations=[],
    )


def _ai_report() -> AiReportView:
    return AiReportView(
        id=_ID,
        scoring_result_id=_ID,
        status=AiReportStatus.PENDING,
        llm_mode="replay",
        model_id=None,
        prompt_version="explain-v1",
        report=None,
        fallback_reason=None,
        updated_at=_NOW,
    )


@manager_router.get(
    "/applications/{application_id}/ai-report", response_model=AiReportView, responses=errors()
)
async def get_ai_report(application_id: UUID) -> AiReportView:
    return _ai_report()


@manager_router.post(
    "/applications/{application_id}/ai-report",
    response_model=AiReportView,
    status_code=202,
    responses=errors(E.INVALID_STATUS_TRANSITION),
    description="Не меняет revision заявки. Сериализация по записи ai_reports; "
    "свежий PENDING возвращается без повторного запуска. Новая генерация использует "
    "generation_id и updated_at (design §3.6). Реализация — #8.",
)
async def regenerate_ai_report(application_id: UUID, regenerate: bool = False) -> AiReportView:
    return _ai_report()


@manager_router.post(
    "/applications/{application_id}/ai-feedback",
    status_code=204,
    responses=errors(),
    description="Не требует и не меняет revision заявки. UPSERT по "
    "(ai_report_id, manager_user_id): повтор заменяет оценку. Не меняет статус, расчёт "
    "и allowed_actions. Реализация — #8.",
)
async def ai_feedback(application_id: UUID, body: AiFeedbackRequest) -> None:
    return None


@manager_router.get("/stats", response_model=ManagerStats, responses=errors())
async def stats() -> ManagerStats:
    return ManagerStats(
        applications_by_status={ApplicationStatus.UNDER_REVIEW: 1},
        median_time_to_decision_seconds=None,
        suggested_action_distribution={SuggestedAction.COUNTER_OFFER_CANDIDATE: 1},
        decisions_matching_suggestion_share=None,
        ai_feedback_up_share={},
    )


ROUTERS = (auth_router, public_router, onboarding_router, client_router, manager_router)
attach_examples(
    ROUTERS
)  # примеры запросов/ответов в OpenAPI — из самих стабов (app/api/examples.py)
