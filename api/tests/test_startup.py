"""Стартовая последовательность контейнера: `alembic upgrade head` и базовый seed."""

from pathlib import Path

import pytest
from alembic.config import Config

from alembic import command
from app import seed
from app.core.db import create_engine

from .conftest import TEST_DATABASE_URL

API_DIR = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_head_is_repeatable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.chdir(API_DIR)
    config = Config(str(API_DIR / "alembic.ini"))
    command.upgrade(config, "head")
    command.upgrade(config, "head")


async def test_base_seed_is_idempotent() -> None:
    engine = create_engine(TEST_DATABASE_URL)
    try:
        for _ in range(2):
            async with engine.begin() as conn:
                await seed.run_base_seed(conn)
    finally:
        await engine.dispose()


async def test_seed_entrypoint_runs_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    await seed.main()
    await seed.main()
