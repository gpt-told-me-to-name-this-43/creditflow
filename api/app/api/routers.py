"""Реализованные роутеры #7 и оставшиеся стабы #8 с примерами OpenAPI.

Реализация переносит маршрут из `app.api.stubs` в свой роутер с теми же путём, моделями
и описанием ошибок; пример ответа строит тот же builder стаба. Примеры привязываются
одним вызовом: пример «issued» карточки менеджера собирается из примера договора.
"""

from app.api.examples import attach_examples
from app.api.stubs import STUB_ROUTERS
from app.applications.router import router as applications_router
from app.manager.router import router as manager_router

IMPLEMENTED_ROUTERS = (applications_router, manager_router)
attach_examples((*IMPLEMENTED_ROUTERS, *STUB_ROUTERS))

__all__ = ["IMPLEMENTED_ROUTERS", "STUB_ROUTERS"]
