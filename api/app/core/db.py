"""Подключение к PostgreSQL, общий `Base` для моделей SQLAlchemy и сессия на запрос.

Транзакции открывает сервис явно (`async with session.begin()`): изменяющая операция —
одна транзакция с `SELECT … FOR UPDATE` (design.md §3.7). Чтение без `begin()` закрывается
откатом при выходе из сессии, поэтому `GET` ничего не фиксирует в БД.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
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
        connect_args={"connect_timeout": 3},
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: после COMMIT ответ строится из уже загруженных объектов
    return async_sessionmaker(engine, expire_on_commit=False)


def sessionmaker_of(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    return sessions


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with sessionmaker_of(request)() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_session)]
