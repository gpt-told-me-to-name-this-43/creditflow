"""Подключение к PostgreSQL, сессия на запрос и общий `Base` для моделей SQLAlchemy.

`Base.metadata` используется Alembic и генератором ER.
"""

from collections.abc import AsyncGenerator

from fastapi import Request
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_pre_ping=True,
        # Значения параметров не попадают в текст исключений SQLAlchemy (#5, логи).
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # Создаётся один раз в lifespan и хранится в app.state.session_factory.
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Сессия на запрос. Транзакцией управляет вызывающий код (`commit()` или
    `async with session.begin()`); незакоммиченное откатывается при закрытии сессии."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session
