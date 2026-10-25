import json
import os
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import AsyncExitStack
from functools import cache
from pathlib import Path
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from argon2 import PasswordHasher

# Ключ подписи для тестов. Задаётся до импорта app.main: модуль создаёт `app` при импорте,
# а Settings без APP_SECRET_KEY не стартует (#5).
TEST_SECRET_KEY = "pytest-only-jwt-secret-0123456789abcdef"
os.environ.setdefault("APP_SECRET_KEY", TEST_SECRET_KEY)

from app.auth.tokens import issue_token  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.db.models import Base, CreditProduct, User  # noqa: E402
from app.seed import DEMO_PASSWORD, DEMO_USERS, PRODUCTS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_SIM_OPENAPI = REPO_ROOT / "docs" / "openapi-ext-sim.json"
EXT_SIM_URL = "http://ext-sim.test"

# Живой PostgreSQL: в CI — сервис postgres:16, локально — `make dev` (db на localhost:5432).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://creditflow:creditflow@localhost:5432/creditflow"
)
# Порт 1 никто не слушает: соединение отклоняется сразу.
DEAD_DATABASE_URL = "postgresql+psycopg://creditflow:x@127.0.0.1:1/creditflow"


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def make(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "database_url": TEST_DATABASE_URL,
            "ext_sim_base_url": EXT_SIM_URL,
            "app_env": "test",
            "app_secret_key": TEST_SECRET_KEY,
        }
        values.update(overrides)
        return Settings(**values)

    return make


def ext_sim_examples() -> dict[str, Any]:
    """Примеры ответов ext-sim из docs/openapi-ext-sim.json: имя схемы → пример."""
    spec = json.loads(EXT_SIM_OPENAPI.read_text(encoding="utf-8"))
    return {
        name: schema["examples"][0]
        for name, schema in spec["components"]["schemas"].items()
        if schema.get("examples")
    }


# --- Демо-учётки в БД и токены (#5) ------------------------------------------------------

CLIENT_LOGIN = "director.techservice@creditflow.demo"
MANAGER_LOGIN = "manager.anna@creditflow.demo"
_ROLES = {user.email: user.role for user in DEMO_USERS}


def demo_user_id(login: str) -> uuid.UUID:
    """Детерминированный id учётки в тестовой БД: токен можно выпустить заранее."""
    return uuid.uuid5(uuid.NAMESPACE_URL, login)


def bearer(login: str) -> dict[str, str]:
    """Токен учётки с id `demo_user_id(login)`; не демо-учётки — CLIENT."""
    token = issue_token(demo_user_id(login), _ROLES.get(login, "CLIENT"), TEST_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


@cache
def _demo_hash() -> str:
    return PasswordHasher().hash(DEMO_PASSWORD)


def reset_database() -> None:
    """Схема на head, все таблицы пусты, кроме продуктов и демо-учёток с фиксированными id.

    TRUNCATE, а не DELETE: insert-only триггеры (#6) построчные и TRUNCATE не ловят.
    """
    engine = sa.create_engine(TEST_DATABASE_URL)
    try:
        with engine.begin() as conn:
            if conn.scalar(sa.text("SELECT to_regclass('users')")) is None:
                _upgrade_head()
            tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
            conn.execute(sa.text(f"TRUNCATE {tables} CASCADE"))
            conn.execute(sa.insert(CreditProduct), list(PRODUCTS))
            conn.execute(
                sa.insert(User),
                [
                    {
                        "id": demo_user_id(u.email),
                        "email": u.email,
                        "role": u.role,
                        "full_name": u.full_name,
                        "person_inn": u.person_inn,
                        "password_hash": _demo_hash(),
                    }
                    for u in DEMO_USERS
                ],
            )
    finally:
        engine.dispose()


def _upgrade_head() -> None:
    from alembic.config import Config

    from alembic import command

    api_dir = Path(__file__).resolve().parents[1]
    config = Config(str(api_dir / "alembic.ini"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    try:
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture
def db_reset() -> None:
    reset_database()


@pytest.fixture
def running() -> Iterator[Callable[[Any], Any]]:
    """Запускает lifespan приложения (пул БД, ExtSimClient) на время теста; после этого
    `TestClient(app)` без контекстного менеджера тоже работает с БД."""
    from fastapi.testclient import TestClient

    clients: list[TestClient] = []

    def start(app: Any) -> Any:
        # Цикл восстановления (#7) держал бы соединения пула в цикле событий lifespan,
        # а запросы TestClient без контекста идут из другого цикла — запрос зависает.
        app.state.recovery_interval = None
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return app

    yield start
    for client in reversed(clients):
        client.__exit__(None, None, None)


@pytest.fixture
async def serve() -> AsyncIterator[Callable[[Any], Awaitable[httpx.AsyncClient]]]:
    """Асинхронный клиент: lifespan и запросы — в цикле событий теста, поэтому запросы
    можно выполнять конкурентно (`asyncio.gather`) на настоящем пуле БД."""
    async with AsyncExitStack() as stack:

        async def start(app: Any) -> httpx.AsyncClient:
            await stack.enter_async_context(app.router.lifespan_context(app))
            transport = httpx.ASGITransport(app=app)
            return await stack.enter_async_context(
                httpx.AsyncClient(transport=transport, base_url="http://testserver")
            )

        yield start
