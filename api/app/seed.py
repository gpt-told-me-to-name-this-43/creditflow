"""Базовый seed (design.md §3.2): продукты и учётки без компаний и заявок.

Запускается при каждом старте `api` и через `make seed`, поэтому обязан быть
идемпотентным: повторный запуск не создаёт дублей и не меняет записи.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.core.db import create_engine

logger = logging.getLogger("app.seed")


async def run_base_seed(conn: AsyncConnection) -> None:
    # TODO(#6): 2 продукта и 10 учёток — после появления таблиц.
    return None


async def main() -> None:
    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await run_base_seed(conn)
    finally:
        await engine.dispose()
    logger.info("base seed: done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main())
