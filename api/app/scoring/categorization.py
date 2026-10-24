"""Категоризация операций по правилам `rules/categorization-v1.yaml` (design.md §3.4).

- Правила читаются и валидируются Pydantic ОДИН раз (`load_rules()` при старте api);
  битый YAML роняет старт, а не конкретный Submit.
- `categorize()` — чистая функция: тот же вход → тот же `(category, rule_id)`.
- Первое сработавшее правило побеждает; ничего не сработало → UNCLASSIFIED.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.enums import TransactionCategory

RULES_PATH = Path(__file__).parent / "rules" / "categorization-v1.yaml"
UNCLASSIFIED_RULE_ID = "unclassified"
_KBK = re.compile(r"кбк\s*(\d{20})")

CounterpartyKind = Literal["LLC", "IE", "BANK", "UNKNOWN"]


def normalize_text(text: str) -> str:
    """Регистр и «ё» не влияют на совпадение: «Оплата по счёту» ~ «по счет»."""
    return text.casefold().replace("ё", "е")


class _When(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: Literal["IN", "OUT"] | None = None
    counterparty_is_bank: bool | None = None
    counterparty_inn_equals: Literal["company_inn", "director_inn"] | None = None
    counterparty_kind: tuple[CounterpartyKind, ...] | None = None
    purpose_regex: str | None = None
    kbk_prefix: str | None = Field(default=None, pattern=r"^\d{1,20}$")

    @field_validator("purpose_regex")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                re.compile(value)
            except re.error as exc:  # re.error не ValueError: Pydantic сам его не обернёт
                raise ValueError(f"невалидный purpose_regex {value!r}: {exc}") from exc
        return value


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z_]+$")
    category: TransactionCategory
    when: _When


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    rules: tuple[Rule, ...] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, rules: tuple[Rule, ...]) -> tuple[Rule, ...]:
        ids = [r.id for r in rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule id должны быть уникальны")
        return rules


@cache
def load_rules(path: Path = RULES_PATH) -> RuleSet:
    """Единственное место с I/O; вызывается при старте (lifespan) и в тестах."""
    return RuleSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class StatementTransaction:
    """Операция выписки во внутреннем виде ядра (адаптер из DTO ExtSimClient — в #7)."""

    external_id: str
    booked_at: date
    direction: Literal["IN", "OUT"]
    amount_rub: Decimal  # всегда > 0
    counterparty_inn: str | None
    counterparty_is_bank: bool
    purpose: str


@dataclass(frozen=True)
class CategorizedTransaction:
    tx: StatementTransaction
    category: TransactionCategory
    rule_id: str


def _kind(tx: StatementTransaction) -> CounterpartyKind:
    if tx.counterparty_is_bank:
        return "BANK"
    if tx.counterparty_inn is None:
        return "UNKNOWN"
    return "LLC" if len(tx.counterparty_inn) == 10 else "IE"


def _matches(
    when: _When, tx: StatementTransaction, purpose: str, company_inn: str, director_inn: str | None
) -> bool:
    if when.direction is not None and tx.direction != when.direction:
        return False
    if (
        when.counterparty_is_bank is not None
        and tx.counterparty_is_bank != when.counterparty_is_bank
    ):
        return False
    if when.counterparty_inn_equals is not None:
        target = company_inn if when.counterparty_inn_equals == "company_inn" else director_inn
        if target is None or tx.counterparty_inn != target:
            return False
    if when.counterparty_kind is not None and _kind(tx) not in when.counterparty_kind:
        return False
    if when.kbk_prefix is not None:
        kbk = _KBK.search(purpose)
        if kbk is None or not kbk.group(1).startswith(when.kbk_prefix):
            return False
    # regex ищется в уже нормализованном тексте; сами шаблоны в YAML — в нижнем регистре и с «е»
    return when.purpose_regex is None or re.search(when.purpose_regex, purpose) is not None


def categorize(
    transactions: Sequence[StatementTransaction],
    rules: RuleSet,
    *,
    company_inn: str,
    director_inn: str | None,
) -> list[CategorizedTransaction]:
    result = []
    for tx in transactions:
        purpose = normalize_text(tx.purpose)
        for rule in rules.rules:
            if _matches(rule.when, tx, purpose, company_inn, director_inn):
                result.append(CategorizedTransaction(tx, rule.category, rule.id))
                break
        else:
            result.append(
                CategorizedTransaction(tx, TransactionCategory.UNCLASSIFIED, UNCLASSIFIED_RULE_ID)
            )
    return result
