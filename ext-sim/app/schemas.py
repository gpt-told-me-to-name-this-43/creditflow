"""Схемы ответов ext-sim (design.md §3.4).

Деньги передаются строками с двумя знаками (`"123.45"`), `float` не используется.
Примеры в схемах — ответы на фикстуре-образце; клиент в `api` валидирует их
своими DTO в контрактном тесте.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[str, Field(pattern=r"^\d+\.\d{2}$", examples=["123.45"])]


class RegistryStatus(StrEnum):
    ACTIVE = "ACTIVE"
    LIQUIDATING = "LIQUIDATING"
    LIQUIDATED = "LIQUIDATED"


class BkiSummaryStatus(StrEnum):
    CLEAN = "CLEAN"
    UNKNOWN = "UNKNOWN"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"


class _Schema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Director(_Schema):
    full_name: str
    inn: str = Field(pattern=r"^\d{12}$")


class EgrulCompany(_Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inn": "0099000014",
                    "ogrn": "1210099000011",
                    "name": "ООО «Образец»",
                    "status": "ACTIVE",
                    "registered_at": "2021-03-15",
                    "okved_main": "10.71",
                    "director": {"full_name": "Образцов Пётр Ильич", "inn": "009900000120"},
                }
            ]
        }
    )

    inn: str = Field(pattern=r"^\d{10}$")
    ogrn: str = Field(pattern=r"^\d{13}$")
    name: str
    status: RegistryStatus
    registered_at: date
    okved_main: str
    director: Director


class EgripEntrepreneur(_Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inn": "009900000200",
                    "ogrnip": "321009900000010",
                    "full_name": "Образцова Анна Сергеевна",
                    "status": "ACTIVE",
                    "registered_at": "2021-06-01",
                    "okved_main": "47.19",
                }
            ]
        }
    )

    inn: str = Field(pattern=r"^\d{12}$")
    ogrnip: str = Field(pattern=r"^\d{15}$")
    full_name: str
    status: RegistryStatus
    registered_at: date
    okved_main: str


class FnsCompanyStatus(_Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "bankruptcy": False,
                    "active_account_blocks": 0,
                    "checked_at": "2026-10-21T09:00:00Z",
                }
            ]
        }
    )

    bankruptcy: bool
    active_account_blocks: int = Field(ge=0)
    checked_at: datetime


class BkiObligation(_Schema):
    creditor_name: str
    monthly_payment_rub: Money
    outstanding_rub: Money


class BkiReportRequest(_Schema):
    inn: str = Field(pattern=r"^\d{10}$|^\d{12}$")
    consent_id: str | None = Field(
        default=None, description="id согласия на запрос в БКИ; без него — 403"
    )


class BkiReport(_Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "report_id": "5b0c3c1e-6f0e-5d55-9a43-8d7b8f3c2a10",
                    "summary_status": "CLEAN",
                    "monthly_payments_total_rub": "45000.00",
                    "obligations": [
                        {
                            "creditor_name": "Банк Образец",
                            "monthly_payment_rub": "45000.00",
                            "outstanding_rub": "900000.00",
                        }
                    ],
                }
            ]
        }
    )

    report_id: str
    summary_status: BkiSummaryStatus
    monthly_payments_total_rub: Money
    obligations: list[BkiObligation]


class Counterparty(_Schema):
    inn: str | None = Field(default=None, pattern=r"^\d{10}$|^\d{12}$")
    name: str
    is_bank: bool


class Transaction(_Schema):
    external_id: str
    booked_at: date
    direction: Literal["IN", "OUT"]
    amount_rub: Money
    counterparty: Counterparty
    purpose: str


class BankStatement(_Schema):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "inn": "0099000014",
                    "account_masked": "40702 •••• 0014",
                    "from": "2026-09-01",
                    "to": "2026-09-30",
                    "transactions": [
                        {
                            "external_id": "0099000014-000003",
                            "booked_at": "2026-09-05",
                            "direction": "IN",
                            "amount_rub": "350000.00",
                            "counterparty": {
                                "inn": "0099000021",
                                "name": "ООО «Покупатель Образца»",
                                "is_bank": False,
                            },
                            "purpose": "Оплата по счёту № 17 от 01.09.2026",
                        }
                    ],
                }
            ]
        },
        populate_by_name=True,
    )

    inn: str
    account_masked: str
    from_: date = Field(alias="from")
    to: date
    transactions: list[Transaction]


class Health(_Schema):
    status: Literal["ok"]


class ErrorBody(_Schema):
    code: str
    message: str
    details: list[dict[str, Any]] | None = None


class ErrorResponse(_Schema):
    error: ErrorBody
