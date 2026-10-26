"""Реализованные роутеры #7 и #8 с примерами OpenAPI.

Реализация перенесла каждый маршрут из стабов контракта v1 в свой роутер с теми же путём,
моделями и описанием ошибок; пример ответа строит builder из `app.api.stubs`. Примеры
привязываются одним вызовом: пример «issued» карточки менеджера собирается из примера договора.
"""

from app.api.examples import attach_examples
from app.applications.router import router as applications_router
from app.manager.router import router as manager_router

IMPLEMENTED_ROUTERS = (applications_router, manager_router)
attach_examples(IMPLEMENTED_ROUTERS)

__all__ = ["IMPLEMENTED_ROUTERS"]
