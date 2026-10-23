"""Точка входа `api`: FastAPI-приложение CreditFlow (design.md §3.2)."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import test_reset
from app.api.examples import preserve_nullable_examples
from app.api.stubs import ROUTERS as CONTRACT_ROUTERS
from app.core.config import AppEnv, Settings
from app.core.db import create_engine
from app.core.errors import install_error_handlers
from app.core.health import router as health_router
from app.extsim_client import ExtSimClient
from app.scoring.categorization import load_rules

API_PREFIX = "/api/v1"
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Правила категоризации валидируются при старте (design §3.4): битый YAML роняет
    # запуск api, а не первый Submit. Делаем это до открытия пула БД и клиента ext-sim.
    app.state.categorization_rules = load_rules()
    app.state.engine = create_engine(settings.database_url)
    app.state.ext_sim = ExtSimClient(settings.ext_sim_base_url)
    try:
        yield
    finally:
        await app.state.ext_sim.aclose()
        await app.state.engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    # Settings() валидирует окружение: в production тестовые флаги роняют старт.
    settings = settings or Settings()
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
            "Сейчас маршруты контракта — фиксированные стабы #6 в local/test: проверяют "
            "только наличие Bearer. JWT/RBAC и владение — #5, бизнес-операции — #7, AI — #8. "
            "В production до реализации этих проверок доступен только health. "
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
    install_error_handlers(app)
    app.include_router(health_router, prefix=API_PREFIX)
    # Стабы контракта v1 (#6); реализации заменяют их по модулям в #5/#7/#8.
    # Стабы контракта #6 не проверяют токен (только наличие Bearer, app/core/security.py)
    # и отдают фиксированные данные. В production их не монтируем вовсе: до #5 маршруты
    # отвечают 404, и стабом нельзя воспользоваться как настоящим API.
    if settings.app_env is AppEnv.PRODUCTION:
        logger.warning("APP_ENV=production: стабы контракта v1 не подключены (до #5)")
    else:
        for router in CONTRACT_ROUTERS:
            app.include_router(router, prefix=API_PREFIX)
    # design §4: при TEST_RESET_ENABLED=false роутер не монтируется вовсе → 404
    if settings.app_env in {AppEnv.LOCAL, AppEnv.TEST} and settings.test_reset_enabled:
        app.include_router(test_reset.router, prefix=API_PREFIX)
    preserve_nullable_examples(app, CONTRACT_ROUTERS, API_PREFIX)
    return app


app = create_app()
