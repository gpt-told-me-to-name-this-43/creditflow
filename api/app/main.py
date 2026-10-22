"""Точка входа `api`: FastAPI-приложение CreditFlow (design.md §3.2)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings
from app.core.db import create_engine
from app.core.health import router as health_router
from app.extsim_client import ExtSimClient

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
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
        summary="MVP кредитного конвейера с AI-assist",
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.include_router(health_router, prefix=API_PREFIX)
    return app


app = create_app()
