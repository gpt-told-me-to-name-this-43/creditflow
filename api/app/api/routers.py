"""Маршруты контракта v1 в порядке OpenAPI: реализованные модули и оставшиеся стабы.

Реализация модуля (#5, #7, #8) переносит маршрут из `app.api.stubs` в свой роутер с теми же
путём, моделями и описанием ошибок; порядок здесь сохраняет порядок путей в docs/openapi.json.
"""

from app.api.examples import attach_examples
from app.api.stubs import (
    auth_router,
    client_router,
    manager_router,
    onboarding_router,
    public_router,
)
from app.applications.router import router as applications_router
from app.manager.router import router as manager_impl_router

ROUTERS = (
    auth_router,
    public_router,
    onboarding_router,
    applications_router,
    client_router,
    manager_impl_router,
    manager_router,
)
# Примеры запросов/ответов в OpenAPI — из builder-функций стабов (app/api/examples.py).
attach_examples(ROUTERS)
