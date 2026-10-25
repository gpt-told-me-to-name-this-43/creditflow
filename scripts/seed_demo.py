"""Демо-состояние через сервисный слой (issue #7): обёртка над app.demo.reset / seed_demo.

Запуск из каталога `api` с переменными окружения api (DATABASE_URL, EXT_SIM_BASE_URL,
APP_SECRET_KEY, APP_AS_OF_DATE):

    uv run python ../scripts/seed_demo.py           # сброс БД + базовый seed + демо
    uv run python ../scripts/seed_demo.py --clean   # сброс + только базовый seed

Обычно вызывается не напрямую, а через `make demo-reset` (POST /_test/reset?mode=demo).
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app.core.config import Settings
from app.core.db import create_engine, create_session_factory
from app.demo.reset import reset_database
from app.extsim_client import ExtSimClient
from app.scoring.categorization import load_rules


async def run(demo: bool) -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    ext_sim = ExtSimClient(settings.ext_sim_base_url)
    started = time.perf_counter()
    try:
        await reset_database(
            engine, create_session_factory(engine), ext_sim, load_rules(), settings, demo=demo
        )
    finally:
        await ext_sim.aclose()
        await engine.dispose()
    print(f"{'demo' if demo else 'clean'}: готово за {time.perf_counter() - started:.1f} с")


def main() -> None:
    parser = argparse.ArgumentParser(description="Сброс БД и демо-состояние")
    parser.add_argument("--clean", action="store_true", help="только базовый seed")
    asyncio.run(run(demo=not parser.parse_args().clean))


if __name__ == "__main__":
    main()
