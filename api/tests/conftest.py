import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
EXT_SIM_OPENAPI = REPO_ROOT / "docs" / "openapi-ext-sim.json"
EXT_SIM_URL = "http://ext-sim.test"

# Живой PostgreSQL: в CI — сервис postgres:16, локально — `make dev` (db на localhost:5432).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://creditflow:creditflow@localhost:5432/creditflow"
)
# Порт 1 никто не слушает: соединение отклоняется сразу.
DEAD_DATABASE_URL = "postgresql+psycopg://creditflow:x@127.0.0.1:1/creditflow"
TEST_SECRET_KEY = "test-only-jwt-secret-0123456789abcdef"


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
