"""Типизированные DTO ответов ext-sim (контракт — docs/openapi-ext-sim.json).

Деньги приходят строками и разбираются в `Decimal`; число в JSON — ошибка контракта.
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator


def _money_from_string(value: object) -> object:
    if not isinstance(value, str):
        raise ValueError("деньги в ответе ext-sim должны быть строкой")
    return value


Money = Annotated[Decimal, BeforeValidator(_money_from_string)]


class RegistryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LIQUIDATING = "LIQUIDATING"
    LIQUIDATED = "LIQUIDATED"


class BkiSummaryStatus(StrEnum):
    CLEAN = "CLEAN"
    UNKNOWN = "UNKNOWN"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"


class _DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Director(_DTO):
    full_name: str
    inn: str


class EgrulCompany(_DTO):
    inn: str
    ogrn: str
    name: str
    status: RegistryStatus
    registered_at: date
    okved_main: str
    director: Director


class EgripEntrepreneur(_DTO):
    inn: str
    ogrnip: str
    full_name: str
    status: RegistryStatus
    registered_at: date
    okved_main: str


class FnsCompanyStatus(_DTO):
    bankruptcy: bool
    active_account_blocks: int
    checked_at: datetime


class BkiObligation(_DTO):
    creditor_name: str
    monthly_payment_rub: Money
    outstanding_rub: Money


class BkiReport(_DTO):
    report_id: str
    summary_status: BkiSummaryStatus
    monthly_payments_total_rub: Money
    obligations: list[BkiObligation]


class Counterparty(_DTO):
    inn: str | None
    name: str
    is_bank: bool


class Transaction(_DTO):
    external_id: str
    booked_at: date
    direction: Literal["IN", "OUT"]
    amount_rub: Money
    counterparty: Counterparty
    purpose: str


class BankStatement(_DTO):
    model_config = ConfigDict(populate_by_name=True)

    inn: str
    account_masked: str
    from_: date = Field(alias="from")
    to: date
    transactions: list[Transaction]


class StatementPeriod(_DTO):
    """Период выписки, обе границы включительно."""

    from_: date
    to: date

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.from_ > self.to:
            raise ValueError("начало периода позже конца")
        return self


RegistryRecord = EgrulCompany | EgripEntrepreneur


class SubmitData(_DTO):
    """Полный набор внешних данных для Submit (design.md §3.7, шаг 3)."""

    registry: RegistryRecord
    fns: FnsCompanyStatus
    bki: BkiReport
    statement: BankStatement
