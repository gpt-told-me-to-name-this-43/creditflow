"""Стабы контракта API v1 (issue #6, тег `contract-v1`).

Каждый эндпоинт из таблицы #6 объявлен с настоящими request/response-моделями
и описанием ошибок, а отвечает фиксированным примером, который проходит его
`response_model`. Фронт генерирует клиент из `docs/openapi.json` и работает на моках,
не дожидаясь бэка. Реализации заменяют стабы по модулям: auth/onboarding — #5,
заявки и решения — #7, AI — #8. Сигнатуры при этом не меняются (иначе — label
`contract-change` и запись в docs/api-changelog.md).

Auth и онбординг реализованы (#5: app/auth, app/onboarding), конвейер заявок — #7
(app/applications, app/manager): здесь их builder-функции примеров OpenAPI и оставшиеся
стабы #8 (interpret, ai-report, ai-feedback). Доступ к ним проверяется по-настоящему: JWT
и роль на уровне роутера (`require_role`, #5), поэтому матрица «роль × эндпоинт» проверяет и стабы.
Данные стабов фиксированные, без владения и состояния, поэтому при APP_ENV=production
стабы не монтируются.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.examples import EXAMPLE_NOW, example_from
from app.applications.catalog import CatalogProduct, match_products
from app.auth.deps import require_role
from app.core.config import Settings
from app.core.errors import errors
from app.core.idempotency import IdempotencyKeyHeader
from app.schemas.auth import Role
from app.schemas.client import (
    AmountSuggestion,
    ApplicationCreate,
    ApplicationPatch,
    ClientAction,
    ClientApplicationView,
    ClientInfoRequest,
    ClientOffer,
    ContractView,
    CreditProduct,
    FieldSource,
    InfoResponseRequest,
    InterpretRequest,
    InterpretResponse,
    InterpretStatus,
    InterpretSuggestions,
    PurposeSuggestion,
    RevisionRequest,
    ScheduleItem,
    SignChallenge,
    SignRequest,
    SubmitRequest,
    TermsField,
    TermSuggestion,
    TimelineEvent,
)
from app.schemas.common import ErrorCode as E
from app.schemas.enums import (
    AiReportStatus,
    ApplicationStatus,
    CalculationStatus,
    ClientReasonCode,
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
    OfferConstraints,
    OfferPreviewResponse,
    Proposal,
    QueueItem,
    RuleTraceItem,
    Scoring,
)
from app.scoring.money import money_str
from app.scoring.schedule import build_schedule
from app.seed import PRODUCTS

IdempotencyKey = IdempotencyKeyHeader

_ID = UUID("7f3e2a10-0000-4000-8000-000000000001")
# Фиксированное время демо-данных (= APP_AS_OF_DATE): прошлые события C2 и OpenAPI-примеры.
# Для того, что должно быть «в будущем» относительно запроса (expires_at), — текущее время.
_NOW = EXAMPLE_NOW

client_router = APIRouter(tags=["client"], dependencies=[Depends(require_role(Role.CLIENT))])
manager_router = APIRouter(
    prefix="/manager", tags=["manager"], dependencies=[Depends(require_role(Role.MANAGER))]
)


def app_settings(request: Request) -> Settings:
    return request.app.state.settings


AppSettings = Annotated[Settings, Depends(app_settings)]


def _client_app(status: ApplicationStatus = ApplicationStatus.DRAFT) -> ClientApplicationView:
    # Только примеры контракта, не runtime FSM. Расчёты теми же чистыми функциями,
    # что и договор; исходные условия C2 сохраняются после принятия оффера.
    accepted = status in {
        ApplicationStatus.APPROVED,
        ApplicationStatus.SIGNED,
        ApplicationStatus.ISSUED,
    }
    amount = Decimal(3_000_000)
    rows = build_schedule(amount, Decimal(24), 36, _NOW.date())
    actions = {
        ApplicationStatus.DRAFT: [ClientAction.EDIT, ClientAction.INTERPRET, ClientAction.SUBMIT],
        ApplicationStatus.NEED_INFO: [ClientAction.RESPOND_INFO],
        ApplicationStatus.COUNTER_OFFER: [ClientAction.ACCEPT_OFFER, ClientAction.DECLINE_OFFER],
        ApplicationStatus.APPROVED: [
            ClientAction.VIEW_CONTRACT,
            ClientAction.REQUEST_SIGN_CODE,
            ClientAction.SIGN,
        ],
        ApplicationStatus.SIGNED: [ClientAction.VIEW_CONTRACT],
        ApplicationStatus.ISSUED: [ClientAction.VIEW_CONTRACT],
    }
    chain = [ApplicationStatus.DRAFT]
    if status is not ApplicationStatus.DRAFT:
        chain.append(ApplicationStatus.UNDER_REVIEW)
        if status is not ApplicationStatus.UNDER_REVIEW:
            if accepted or status is ApplicationStatus.DECLINED:
                chain.append(ApplicationStatus.COUNTER_OFFER)
            if status in {ApplicationStatus.SIGNED, ApplicationStatus.ISSUED}:
                chain.append(ApplicationStatus.APPROVED)
            if status is ApplicationStatus.ISSUED:
                chain.append(ApplicationStatus.SIGNED)
            chain.append(status)
    offer_rows = build_schedule(Decimal(2_340_000), Decimal(24), 36, _NOW.date())
    return ClientApplicationView(
        id=_ID,
        revision=len(chain),
        status=status,
        purpose_text="Купить печь за 3 млн на 3 года",
        purpose_code=PurposeCode.EQUIPMENT,
        requested_amount_rub=money_str(amount),
        term_months=36,
        product_id="investment",
        terms_source=TermsSource.RULES_CONFIRMED,
        terms_field_sources={
            TermsField.PURPOSE_CODE: FieldSource.RULES,
            TermsField.REQUESTED_AMOUNT_RUB: FieldSource.RULES,
            TermsField.TERM_MONTHS: FieldSource.MANUAL,
        },
        allowed_actions=actions.get(status, []),
        annual_rate_pct="24.00",
        monthly_payment_rub=money_str(rows[0].payment_rub),
        overpayment_rub=money_str(sum((r.interest_rub for r in rows), Decimal(0))),
        submitted_at=_NOW + timedelta(minutes=1) if status is not ApplicationStatus.DRAFT else None,
        client_reason_code=(
            ClientReasonCode.HIGH_DEBT_LOAD if status is ApplicationStatus.REJECTED else None
        ),
        offer=ClientOffer(
            amount_rub="2340000.00",
            term_months=36,
            annual_rate_pct="24.00",
            monthly_payment_rub=money_str(offer_rows[0].payment_rub),
            overpayment_rub=money_str(sum((r.interest_rub for r in offer_rows), Decimal(0))),
        )
        if status in {ApplicationStatus.COUNTER_OFFER, ApplicationStatus.DECLINED} or accepted
        else None,
        info_request=ClientInfoRequest(
            question_text="Подтвердите стоимость печи", answer_text=None, answered_at=None
        )
        if status is ApplicationStatus.NEED_INFO
        else None,
        timeline=[
            TimelineEvent(
                from_status=chain[i - 1] if i else None,
                to_status=step,
                created_at=_NOW + timedelta(minutes=i),
            )
            for i, step in enumerate(chain)
        ],
    )


# --- Клиент (#7, #9) -------------------------------------------------------------------


def _build_credit_products(
    purpose: PurposeCode | None = PurposeCode.EQUIPMENT,
    amount: int | None = 3_000_000,
    term: int | None = 36,
) -> list[CreditProduct]:
    """Пример ответа: каталог — `seed.PRODUCTS` (тот же, что в БД), подбор —
    та же функция `match_products`, что у реализации (app/applications/router.py).
    Значения по умолчанию — запрос C2 для примера OpenAPI."""
    return match_products([CatalogProduct.from_seed(p) for p in PRODUCTS], purpose, amount, term)


def _build_create_application(body: ApplicationCreate) -> ClientApplicationView:
    return _client_app().model_copy(
        update={
            "purpose_text": body.purpose_text,
            "purpose_code": None,
            "requested_amount_rub": None,
            "term_months": None,
            "product_id": None,
            "terms_source": TermsSource.MANUAL,
            "terms_field_sources": {},
            "annual_rate_pct": None,
            "monthly_payment_rub": None,
            "overpayment_rub": None,
            "allowed_actions": [ClientAction.EDIT, ClientAction.INTERPRET],
        }
    )


def _build_list_applications() -> list[ClientApplicationView]:
    return [_client_app()]


def _build_get_application(
    status: ApplicationStatus = ApplicationStatus.DRAFT,
) -> ClientApplicationView:
    return _client_app(status)


def _build_patch_application(body: ApplicationPatch) -> ClientApplicationView:
    return _client_app().model_copy(update={"revision": body.revision + 1})


def _build_interpret() -> InterpretResponse:
    return InterpretResponse(
        status=InterpretStatus.OK,
        suggestion=InterpretSuggestions(
            purpose_code=PurposeSuggestion(
                value=PurposeCode.EQUIPMENT, source=FieldSource.RULES, matched_text="печь"
            ),
            requested_amount_rub=AmountSuggestion(
                value=3_000_000, source=FieldSource.RULES, matched_text="3 млн"
            ),
            term_months=TermSuggestion(
                value=36, source=FieldSource.RULES, matched_text="на 3 года"
            ),
        ),
        clarification_question=None,
    )


@client_router.post(
    "/applications/{application_id}/interpret",
    response_model=InterpretResponse,
    responses=errors(E.COMPANY_NOT_BOUND, E.INVALID_STATUS_TRANSITION),
    description="Распознаёт потребность без записи в заявку и без revision. "
    "RULES/LLM — источник каждого предложения. NEEDS_CLARIFICATION содержит вопрос; "
    "UNAVAILABLE оставляет доступным ручной ввод. Сбой LLM — 200 с правилами либо UNAVAILABLE. "
    "Сохранение — отдельный PATCH после явного подтверждения. UI #9 ограничивает ввод "
    "1000 символами; API использует тот же предел.",
)
@example_from(_build_interpret)
async def interpret(application_id: UUID, body: InterpretRequest) -> InterpretResponse:
    return _build_interpret()


def _build_submit(body: SubmitRequest) -> ClientApplicationView:
    return _client_app(ApplicationStatus.UNDER_REVIEW).model_copy(
        update={"revision": body.revision + 1}
    )


def _build_info_response(body: InfoResponseRequest) -> ClientApplicationView:
    view = _client_app(ApplicationStatus.NEED_INFO)
    return view.model_copy(
        update={
            "revision": body.revision + 1,
            "status": ApplicationStatus.UNDER_REVIEW,
            "allowed_actions": [],
            "info_request": ClientInfoRequest(
                question_text="Подтвердите стоимость печи",
                answer_text=body.answer_text,
                answered_at=_NOW + timedelta(minutes=3),
            ),
            "timeline": [
                *view.timeline,
                TimelineEvent(
                    from_status=ApplicationStatus.NEED_INFO,
                    to_status=ApplicationStatus.UNDER_REVIEW,
                    created_at=_NOW + timedelta(minutes=3),
                ),
            ],
        }
    )


def _build_offer_accept(body: RevisionRequest) -> ClientApplicationView:
    return _client_app(ApplicationStatus.APPROVED).model_copy(
        update={"revision": body.revision + 1}
    )


def _build_offer_decline(body: RevisionRequest) -> ClientApplicationView:
    return _client_app(ApplicationStatus.DECLINED).model_copy(
        update={"revision": body.revision + 1}
    )


def _build_contract() -> ContractView:
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
        key_terms_markdown=(
            "## Основные условия\nСумма: 2 340 000 ₽. Срок: 36 месяцев. "
            "Ставка: 24% годовых.\nПогашение ежемесячно по приложенному графику. Демо-договор."
        ),
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


SIGN_CHALLENGE_TTL = timedelta(minutes=5)  # design §3.5: TTL кода подписания 5 минут


def _build_sign_challenge(
    settings: Settings, now: datetime, body: RevisionRequest
) -> SignChallenge:
    """`now` передаёт вызывающий: endpoint — текущее время (challenge не должен быть
    просрочен в момент выдачи), генератор OpenAPI — фиксированное EXAMPLE_NOW."""
    return SignChallenge(
        challenge_id=_ID,
        revision=body.revision + 1,
        expires_at=now + SIGN_CHALLENGE_TTL,
        attempts_remaining=3,
        demo_code="123456" if settings.demo_auth_enabled else None,
    )


def _build_sign(body: SignRequest) -> ClientApplicationView:
    return _client_app(ApplicationStatus.SIGNED).model_copy(update={"revision": body.revision + 1})


# --- Менеджер (#7, #8, #10) ------------------------------------------------------------


def _build_queue() -> list[QueueItem]:
    return [
        QueueItem(
            id=_ID,
            company_name="ООО «Пекарня Плюс»",
            company_inn="0099020010",
            product_id="investment",
            status=ApplicationStatus.UNDER_REVIEW,
            submitted_at=_NOW,
            requested_amount_rub="3000000.00",
            term_months=36,
            suggested_action=SuggestedAction.COUNTER_OFFER_CANDIDATE,
            blocking_codes=[],
        )
    ]


def _build_manager_card(application_id: UUID) -> ManagerApplicationView:
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
        account_history_months=12,
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
        legal_form="LLC",
        okved_main="10.71",
        registered_at=date(2023, 10, 21),
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
        offer_constraints=OfferConstraints(
            min_amount_rub="100000.00",
            max_amount_rub="5000000.00",
            min_term_months=12,
            max_term_months=60,
        ),
        ai_report=_ai_report(),
        decisions=[],
        offers=[],
        info_requests=[],
        contract=None,
        sign_challenges=[],
        timeline=[],
    )


def _build_decisions(body: DecisionRequest) -> DecisionResponse:
    statuses = {
        ManagerAction.APPROVE: ApplicationStatus.APPROVED,
        ManagerAction.COUNTER_OFFER: ApplicationStatus.COUNTER_OFFER,
        ManagerAction.REQUEST_INFO: ApplicationStatus.NEED_INFO,
        ManagerAction.REJECT: ApplicationStatus.REJECTED,
    }
    return DecisionResponse(
        decision_id=_ID, status=statuses[body.action], revision=body.revision + 1
    )


def _build_offer_preview() -> OfferPreviewResponse:
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


def _build_get_ai_report() -> AiReportView:
    return _ai_report()


@manager_router.get(
    "/applications/{application_id}/ai-report", response_model=AiReportView, responses=errors()
)
@example_from(_build_get_ai_report)
async def get_ai_report(application_id: UUID) -> AiReportView:
    return _build_get_ai_report()


def _build_regenerate_ai_report() -> AiReportView:
    return _ai_report()


@manager_router.post(
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
    "generation_id и updated_at (design §3.6). Реализация — #8.",
)
@example_from(_build_regenerate_ai_report)
async def regenerate_ai_report(application_id: UUID, regenerate: bool = False) -> AiReportView:
    return _build_regenerate_ai_report()


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


def _build_stats() -> ManagerStats:
    return ManagerStats(
        applications_by_status={ApplicationStatus.UNDER_REVIEW: 1},
        median_time_to_decision_seconds=None,
        suggested_action_distribution={SuggestedAction.COUNTER_OFFER_CANDIDATE: 1},
        decisions_matching_suggestion_share=None,
        ai_feedback_up_share={},
        ai_feedback_groups=[],
    )


STUB_ROUTERS = (client_router, manager_router)
