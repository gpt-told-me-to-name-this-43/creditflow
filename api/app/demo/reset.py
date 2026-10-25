"""Сброс БД для тестов и демо (issue #7, design §4 «Тестовые эндпоинты»).

- `clean` — пустые таблицы и только базовый seed: продукты и непривязанные пользователи.
  По умолчанию для системных тестов, e2e и `bru run`.
- `demo` — базовый seed + демо-состояние (`run_demo_seed`). `make demo-reset`.
Два сброса подряд дают одинаковое состояние: номера договоров начинаются заново.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.demo.seed_demo import run_demo_seed
from app.extsim_client import ExtSimClient
from app.scoring.categorization import RuleSet
from app.seed import run_base_seed

TABLES = (
    "ai_feedback, ai_reports, sign_challenges, contracts, info_requests, offers, "
    "credit_decisions, decision_proposals, application_events, idempotency_keys, "
    "account_transactions, external_snapshots, consents, scoring_results, applications, "
    "users, companies, credit_products"
)


async def reset_database(
    engine: AsyncEngine,
    sessions: async_sessionmaker[AsyncSession],
    ext_sim: ExtSimClient,
    rules: RuleSet,
    settings: Settings,
    *,
    demo: bool,
) -> None:
    async with engine.begin() as conn:
        # TRUNCATE не вызывает insert-only триггеры (они на UPDATE/DELETE)
        await conn.execute(text(f"TRUNCATE {TABLES}"))
        await conn.execute(text("ALTER SEQUENCE contract_number_seq RESTART WITH 1"))
        await run_base_seed(conn)
    if demo:
        await run_demo_seed(sessions, ext_sim, rules, settings)
