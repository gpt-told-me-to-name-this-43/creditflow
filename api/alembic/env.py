"""Alembic: миграции по `Base.metadata` (модели — app/db/models.py)."""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

import app.db.models  # noqa: F401 — регистрирует таблицы в Base.metadata (иначе autogenerate пуст)
from alembic import context
from app.core.config import Settings
from app.core.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
database_url = Settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
