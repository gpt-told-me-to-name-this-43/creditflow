"""Точка входа `api`: FastAPI-приложение CreditFlow (design.md §3.2)."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.api import test_reset
from app.api.examples import preserve_nullable_examples
from app.api.routers import IMPLEMENTED_ROUTERS
from app.applications.ai_reports import recover_stale_ai_reports
from app.auth.router import router as auth_router
from app.contracts.service import DISBURSE_DELAY_SECONDS, recover_pending_disbursements
from app.core.config import AppEnv, Settings
from app.core.db import create_engine, create_session_factory
from app.core.errors import install_error_handlers
from app.core.health import router as health_router
from app.core.idempotency import install_idempotency
from app.core.logs import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import RateLimits
from app.extsim_client import ExtSimClient
from app.llm.client import build_llm_client, insecure_url_warning
from app.onboarding.consents import current_consents
from app.onboarding.router import public_router as consents_router
from app.onboarding.router import router as onboarding_router
from app.scoring.categorization import load_rules

API_PREFIX = "/api/v1"
RECOVERY_INTERVAL_SECONDS = 15.0
logger = get_logger("app.main")

# Настоящие роутеры #5, #7 и #8 монтируются в любом окружении.
ACCESS_ROUTERS: tuple[APIRouter, ...] = (
    auth_router,
    consents_router,
    onboarding_router,
    *IMPLEMENTED_ROUTERS,
)
CONTRACT_ROUTERS = ACCESS_ROUTERS  # весь контракт v1 реализован: стабов не осталось


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Правила категоризации валидируются при старте (design §3.4): битый YAML роняет
    # запуск api, а не первый Submit. Делаем это до открытия пула БД и клиента ext-sim.
    app.state.categorization_rules = load_rules()
    current_consents()  # тексты согласий — тоже при старте
    app.state.engine = create_engine(settings.database_url)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.disburse_delay = DISBURSE_DELAY_SECONDS
    app.state.ext_sim = ExtSimClient(settings.ext_sim_base_url)
    # LLM не обязательна: клиент создаётся без обращения к провайдеру (#8)
    app.state.llm = build_llm_client(settings)
    if warning := insecure_url_warning(settings):
        logger.warning(warning)
    # design §3.2: фоновые процессы восстанавливаются при старте и раз в 15 с.
    # None в app.state.recovery_interval (тесты) отключает цикл.
    interval: float | None = getattr(app.state, "recovery_interval", RECOVERY_INTERVAL_SECONDS)
    recovery = asyncio.create_task(_recovery_loop(app, interval)) if interval is not None else None
    try:
        yield
    finally:
        if recovery is not None:
            recovery.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await recovery
        await app.state.ext_sim.aclose()
        aclose = getattr(app.state.llm, "aclose", None)
        if aclose is not None:
            await aclose()
        await app.state.engine.dispose()


async def recover_once(app: FastAPI) -> None:
    """Идемпотентно закрывает зависшие AI-заключения и выдачи. Сбой БД не роняет api."""
    settings: Settings = app.state.settings
    try:
        await recover_stale_ai_reports(
            app.state.session_factory, settings.llm_report_deadline_seconds
        )
        await recover_pending_disbursements(app.state.session_factory)
    except Exception:
        logger.exception("recovery: проход не удался, повтор в следующем цикле")


async def _recovery_loop(app: FastAPI, interval: float) -> None:
    while True:
        await recover_once(app)
        await asyncio.sleep(interval)


def create_app(settings: Settings | None = None) -> FastAPI:
    # Settings() валидирует окружение: в production тестовые флаги роняют старт.
    settings = settings or Settings()
    configure_logging()
    app = FastAPI(
        title="CreditFlow API",
        version="1.0.0",
        summary="MVP кредитного конвейера с AI-assist",
        description=(
            "Контракт API v1 для клиентского и менеджерского кабинетов (design.md §3.7, #9). "
            "Все пути уже включают /api/v1: baseUrl клиента — origin без этого суффикса. "
            "Деньги и DSCR в ответах — десятичные строки, входные суммы — целые рубли. "
            "Время — UTC, отображение в Europe/Moscow. Ошибки — ErrorEnvelope, кроме health. "
            "PATCH и команды состояния передают revision; при 409 REVISION_CONFLICT "
            "нужно перечитать заявку, сохранив ввод. Idempotency-Key обязателен только там, "
            "где объявлен: новый на действие, тот же при сетевом повторе; ошибки не кешируются. "
            "Interpret и preview не сохраняют данные. GET никогда не меняет состояние. "
            "Кнопки клиента определяет allowed_actions; polling каждые 5 с, в SIGNED — 2 с, "
            "завершается при ISSUED/REJECTED/DECLINED. "
            "Вход, роли и онбординг реализованы (#5): JWT HS256 и роль проверяются у каждого "
            "защищённого маршрута. Конвейер заявок реализован (#7), AI-assist — #8: "
            "interpret (правила + LLM, заявку не меняет), ai-report "
            "(PENDING → READY/FALLBACK) и ai-feedback. "
            "Тестовый reset не входит в публикуемый контракт."
        ),
        servers=[{"url": "/", "description": "Текущий origin: SPA и API за nginx"}],
        openapi_tags=[
            {"name": "auth", "description": "Вход и текущий пользователь; me требует Bearer"},
            {"name": "onboarding", "description": "Согласия публичны; компания — роль CLIENT"},
            {"name": "client", "description": "Кабинет CLIENT; свои заявки, чужие — 404"},
            {"name": "manager", "description": "Очередь, решения и AI; роль MANAGER"},
        ],
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.rate_limits = RateLimits()
    install_error_handlers(app)
    install_idempotency(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router, prefix=API_PREFIX)
    for router in ACCESS_ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    if settings.app_env is AppEnv.PRODUCTION and settings.demo_auth_enabled:
        logger.warning("APP_ENV=production: DEMO_AUTH_ENABLED=true — демо-учётки и demo_code")
    # design §4: при TEST_RESET_ENABLED=false роутер не монтируется вовсе → 404
    if settings.app_env in {AppEnv.LOCAL, AppEnv.TEST} and settings.test_reset_enabled:
        app.include_router(test_reset.router, prefix=API_PREFIX)
    preserve_nullable_examples(app, ACCESS_ROUTERS, API_PREFIX)
    return app


app = create_app()
