"""JWT демо-учётки для ручной проверки API до #5 (вход и привязка компании ещё стабы).

Запуск из каталога `api` с переменными из `.env` (так делает `make dev-token`):

    uv run python ../scripts/dev_token.py director.bakery@creditflow.demo --bind 0099020010

`--bind` привязывает компанию из фикстуры ext-sim напрямую в БД (идемпотентно).
Печатает только токен — удобно для `TOKEN=$(make -s dev-token ...)`.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import sqlalchemy as sa

from app.core.config import Settings
from app.core.db import create_engine
from app.core.security import encode_token
from app.schemas.auth import Role

FIXTURES = Path(__file__).resolve().parents[1] / "ext-sim" / "fixtures"


def registry_record(inn: str) -> dict[str, str]:
    folder = FIXTURES / inn
    if len(inn) == 10:
        data = json.loads((folder / "egrul.json").read_text(encoding="utf-8"))
        name, legal_form = data["name"], "LLC"
    else:
        data = json.loads((folder / "egrip.json").read_text(encoding="utf-8"))
        name, legal_form = f"ИП {data['full_name']}", "IE"
    return {
        "inn": inn,
        "legal_form": legal_form,
        "name": name,
        "okved_main": data["okved_main"],
        "registered_at": data["registered_at"],
    }


async def run(email: str, bind: str | None) -> str:
    settings = Settings()
    engine = create_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            user = (
                await conn.execute(
                    sa.text("SELECT id, role FROM users WHERE email = :e"), {"e": email}
                )
            ).one_or_none()
            if user is None:
                sys.exit(f"нет учётки {email}: выполните make seed")
            if bind:
                company_id = await conn.scalar(
                    sa.text(
                        "INSERT INTO companies (inn, legal_form, name, okved_main, registered_at) "
                        "VALUES (:inn, :legal_form, :name, :okved_main, "
                        "CAST(:registered_at AS date)) "
                        "ON CONFLICT (inn) DO UPDATE SET inn = EXCLUDED.inn RETURNING id"
                    ),
                    registry_record(bind),
                )
                await conn.execute(
                    sa.text("UPDATE users SET company_id = :c WHERE id = :u"),
                    {"c": company_id, "u": user.id},
                )
    finally:
        await engine.dispose()
    return encode_token(user.id, Role(user.role), settings.app_secret_key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--bind", metavar="INN", help="привязать компанию из ext-sim/fixtures")
    args = parser.parse_args()
    print(asyncio.run(run(args.email, args.bind)))


if __name__ == "__main__":
    main()
