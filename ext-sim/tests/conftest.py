import json
import shutil
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.fixtures import DEFAULT_FIXTURES_DIR
from app.main import create_app

SAMPLE_INN = "0099000014"
IE_INN = "009900000200"

IE_RECORD = {
    "inn": IE_INN,
    "ogrnip": "321009900000010",
    "full_name": "Образцова Анна Сергеевна",
    "status": "ACTIVE",
    "registered_at": "2021-06-01",
    "okved_main": "47.19",
}


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Копия реальных фикстур плюс ИП-образец для тестов ЕГРИП."""
    root = tmp_path / "fixtures"
    shutil.copytree(DEFAULT_FIXTURES_DIR, root, ignore=shutil.ignore_patterns("*.md"))
    (root / IE_INN).mkdir()
    (root / IE_INN / "egrip.json").write_text(json.dumps(IE_RECORD), encoding="utf-8")
    return root


@pytest.fixture
def make_client(fixtures_dir: Path) -> Callable[[FastAPI], httpx.AsyncClient]:
    def make(app: FastAPI) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sim")

    return make


@pytest.fixture
async def client(
    fixtures_dir: Path, make_client: Callable[[FastAPI], httpx.AsyncClient]
) -> AsyncIterator[httpx.AsyncClient]:
    async with make_client(create_app(fixtures_dir)) as c:
        yield c


@pytest.fixture
def add_company(fixtures_dir: Path) -> Callable[[str, dict[str, Any]], Path]:
    """Добавляет копию образца под новым ИНН с переопределёнными файлами."""

    def add(inn: str, files: dict[str, Any]) -> Path:
        target = fixtures_dir / inn
        shutil.copytree(fixtures_dir / SAMPLE_INN, target)
        egrul = json.loads((target / "egrul.json").read_text(encoding="utf-8"))
        egrul["inn"] = inn
        (target / "egrul.json").write_text(json.dumps(egrul), encoding="utf-8")
        for name, content in files.items():
            (target / name).write_text(json.dumps(content), encoding="utf-8")
        return target

    return add
