"""Стартовая последовательность: `alembic upgrade head`, базовый seed, загрузка правил."""

from collections.abc import Callable
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError

from alembic import command
from app import main, seed
from app.core.config import Settings
from app.core.db import create_engine
from app.scoring import categorization

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


def test_invalid_categorization_rules_abort_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_settings: Callable[..., Settings]
) -> None:
    """issue #6: невалидный YAML правил останавливает старт api (lifespan), а не Submit."""
    broken = tmp_path / "categorization-v1.yaml"
    broken.write_text("version: v1\nrules:\n  - id: Bad-Id\n    category: NOPE\n", "utf-8")
    monkeypatch.setattr(main, "load_rules", lambda: categorization.load_rules(broken))
    with pytest.raises(ValidationError), TestClient(main.create_app(make_settings())):
        pass


def test_startup_loads_categorization_rules(make_settings: Callable[..., Settings]) -> None:
    with TestClient(main.create_app(make_settings())) as client:
        rules = client.app.state.categorization_rules  # type: ignore[attr-defined]
    assert rules is categorization.load_rules()
