"""Базовый seed (design.md §3.2): продукты и учётки без компаний и заявок.

Запускается при каждом старте `api` и через `make seed`, поэтому обязан быть
идемпотентным: повторный запуск не создаёт дублей и не меняет записи.
"""

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal

from argon2 import PasswordHasher
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import Settings
from app.core.db import create_engine
from app.db.models import CreditProduct, User
from app.schemas.enums import PurposeCode as P

logger = logging.getLogger("app.seed")

# Общий пароль демо-учёток: показывается на экране входа только при DEMO_AUTH_ENABLED=true.
# В БД хранится лишь argon2-хеш.
DEMO_PASSWORD = "creditflow-demo"

# Каталог design §3.3; ставка 24% = ключевая 14% + 10 п.п. (design §3.4 «Ставки»).
PRODUCTS = (
    {
        "id": "investment",
        "name": "Инвестиционный кредит",
        "allowed_purposes": [P.EQUIPMENT, P.RENOVATION, P.BUSINESS_EXPANSION],
        "min_amount_rub": Decimal(100_000),
        "max_amount_rub": Decimal(5_000_000),
        "min_term_months": 12,
        "max_term_months": 60,
        "annual_rate_pct": Decimal(24),
    },
    {
        "id": "working_capital",
        "name": "Оборотный кредит",
        "allowed_purposes": [P.INVENTORY, P.SUPPLIERS, P.WORKING_CAPITAL],
        "min_amount_rub": Decimal(100_000),
        "max_amount_rub": Decimal(3_000_000),
        "min_term_months": 3,
        "max_term_months": 24,
        "annual_rate_pct": Decimal(24),
    },
)


@dataclass(frozen=True)
class DemoUser:
    email: str
    role: str
    full_name: str
    person_inn: str | None  # 12 цифр; у менеджеров нет


# 7 директоров + бухгалтер + 2 менеджера (issue #6). ФИО и ИНН директоров совпадают с
# реестровыми фикстурами ext-sim (scripts/gen_registry_ids.py) — иначе привязка по ИНН
# не пройдёт; это проверяет tests/test_db.py::test_directors_match_registry_fixtures.
DEMO_USERS = (
    DemoUser(
        "director.techservice@creditflow.demo", "CLIENT", "Иванов Пётр Сергеевич", "009901001052"
    ),
    DemoUser(
        "director.bakery@creditflow.demo", "CLIENT", "Кузнецова Анна Михайловна", "009902001009"
    ),
    DemoUser("ip.sokolova@creditflow.demo", "CLIENT", "Соколова Алёна Викторовна", "009903001040"),
    DemoUser(
        "director.newstart@creditflow.demo", "CLIENT", "Новиков Станислав Олегович", "009904001090"
    ),
    DemoUser(
        "director.vector@creditflow.demo", "CLIENT", "Векторов Андрей Игоревич", "009905001039"
    ),
    DemoUser(
        "director.sklad@creditflow.demo", "CLIENT", "Складов Михаил Дмитриевич", "009906001088"
    ),
    DemoUser("ip.orlov@creditflow.demo", "CLIENT", "Орлов Дмитрий Степанович", "009907001027"),
    # не руководитель «Пекарни Плюс»: привязка её ИНН → 403 APPLICANT_NOT_AUTHORIZED (#5)
    DemoUser(
        "accountant.bakery@creditflow.demo", "CLIENT", "Бухгалтерова Ольга Ивановна", "009902002059"
    ),
    DemoUser("manager.anna@creditflow.demo", "MANAGER", "Анна Менеджерова", None),
    DemoUser("manager.oleg@creditflow.demo", "MANAGER", "Олег Менеджеров", None),
)


async def run_base_seed(conn: AsyncConnection) -> None:
    """Идемпотентно: ON CONFLICT DO NOTHING — существующие записи не трогаются вовсе
    (в том числе не перехешируется пароль), повторный запуск ничего не меняет."""
    await conn.execute(
        insert(CreditProduct).values(PRODUCTS).on_conflict_do_nothing(index_elements=["id"])
    )
    hasher = PasswordHasher()
    rows = [
        {
            "email": u.email,
            "role": u.role,
            "full_name": u.full_name,
            "person_inn": u.person_inn,
            "password_hash": hasher.hash(DEMO_PASSWORD),
        }
        for u in DEMO_USERS
    ]
    await conn.execute(insert(User).values(rows).on_conflict_do_nothing(index_elements=["email"]))


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
