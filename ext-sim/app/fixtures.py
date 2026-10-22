"""Загрузка фикстур `fixtures/<inn>/` (формат — fixtures/README.md).

Все фикстуры читаются и валидируются при старте: битая фикстура роняет запуск,
а не отдельный запрос.
"""

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import (
    BkiObligation,
    BkiSummaryStatus,
    EgripEntrepreneur,
    EgrulCompany,
    FnsCompanyStatus,
    Money,
    Transaction,
)

DEFAULT_FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_INN_DIR = re.compile(r"^\d{10}$|^\d{12}$")


class Source(StrEnum):
    EGRUL = "egrul"
    EGRIP = "egrip"
    FNS = "fns"
    BKI = "bki"
    BANK = "bank"


class FailKind(StrEnum):
    TIMEOUT = "timeout"
    HTTP_500 = "500"
    HTTP_503 = "503"


class _Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BkiFixture(_Fixture):
    summary_status: BkiSummaryStatus
    monthly_payments_total_rub: Money
    obligations: list[BkiObligation]


class StatementFixture(_Fixture):
    account_masked: str
    transactions: list[Transaction]


class MetaFixture(_Fixture):
    fail_mode: str | None = Field(default=None, description="<источник>_<timeout|500|503>")


@dataclass(frozen=True)
class CompanyFixture:
    inn: str
    egrul: EgrulCompany | None
    egrip: EgripEntrepreneur | None
    fns: FnsCompanyStatus | None
    bki: BkiFixture | None
    statement: StatementFixture | None
    fail_mode: tuple[Source, FailKind] | None


def parse_fail_mode(value: str) -> tuple[Source, FailKind]:
    source, sep, kind = value.partition("_")
    if not sep:
        raise ValueError(f"fail_mode {value!r}: ожидается <источник>_<timeout|500|503>")
    return Source(source), FailKind(kind)


def _read(path: Path) -> Any | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_company(directory: Path) -> CompanyFixture:
    inn = directory.name
    raw = {name: _read(directory / f"{name}.json") for name in ("egrul", "egrip", "fns", "bki")}
    statement = _read(directory / "statement.json")
    meta = MetaFixture.model_validate(_read(directory / "meta.json") or {})

    egrul = EgrulCompany.model_validate(raw["egrul"]) if raw["egrul"] is not None else None
    egrip = EgripEntrepreneur.model_validate(raw["egrip"]) if raw["egrip"] is not None else None
    record = egrul or egrip
    if record is None or (egrul and egrip):
        raise ValueError(f"{directory}: нужен ровно один из egrul.json и egrip.json")
    if record.inn != inn:
        raise ValueError(f"{directory}: ИНН в реестровой записи не совпадает с каталогом")

    return CompanyFixture(
        inn=inn,
        egrul=egrul,
        egrip=egrip,
        fns=FnsCompanyStatus.model_validate(raw["fns"]) if raw["fns"] is not None else None,
        bki=BkiFixture.model_validate(raw["bki"]) if raw["bki"] is not None else None,
        statement=StatementFixture.model_validate(statement) if statement is not None else None,
        fail_mode=parse_fail_mode(meta.fail_mode) if meta.fail_mode else None,
    )


def load_fixtures(root: Path) -> dict[str, CompanyFixture]:
    companies: dict[str, CompanyFixture] = {}
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        if not _INN_DIR.match(directory.name):
            raise ValueError(f"{directory}: имя каталога должно быть ИНН (10 или 12 цифр)")
        companies[directory.name] = _load_company(directory)
    return companies
