"""Реестр кодов ядра (design.md §3.4): вид, описание для менеджера, причина для клиента.

На реестр опираются карточка менеджера, шаблоны клиентских текстов и валидатор
AI-заключения (#8: «коды ⊆ кодов расчёта, каждый риск-код покрыт»). Тест проверяет,
что каждый член `ReasonCode` и `StopFactor` здесь описан.
"""

from dataclasses import dataclass
from enum import StrEnum

from app.schemas.enums import ClientReasonCode, ReasonCode, StopFactor


class CodeKind(StrEnum):
    RISK = "RISK"
    POSITIVE = "POSITIVE"
    STOP = "STOP"


@dataclass(frozen=True)
class CodeInfo:
    kind: CodeKind
    manager_text: str
    client_reason_code: ClientReasonCode | None = None  # только у стоп-факторов


REASON_CODES: dict[ReasonCode, CodeInfo] = {
    ReasonCode.DSCR_BELOW_ONE: CodeInfo(
        CodeKind.RISK, "DSCR ниже 1.00: денежного потока не хватает на платежи"
    ),
    ReasonCode.DSCR_BELOW_TARGET: CodeInfo(CodeKind.RISK, "DSCR ниже целевого 1.25"),
    ReasonCode.CREDIT_HISTORY_SERIOUS: CodeInfo(
        CodeKind.RISK, "Серьёзные нарушения в кредитной истории"
    ),
    ReasonCode.CREDIT_HISTORY_MINOR: CodeInfo(
        CodeKind.RISK, "Незначительные нарушения в кредитной истории"
    ),
    ReasonCode.CREDIT_HISTORY_UNKNOWN: CodeInfo(CodeKind.RISK, "Кредитная история отсутствует"),
    ReasonCode.REVENUE_DECLINE: CodeInfo(CodeKind.RISK, "Выручка снизилась (до 15%)"),
    ReasonCode.REVENUE_SHARP_DECLINE: CodeInfo(CodeKind.RISK, "Выручка снизилась более чем на 15%"),
    ReasonCode.YOUNG_BUSINESS: CodeInfo(CodeKind.RISK, "Бизнесу меньше 24 месяцев"),
    ReasonCode.DSCR_MEETS_TARGET: CodeInfo(CodeKind.POSITIVE, "DSCR не ниже целевого 1.25"),
    ReasonCode.CLEAN_CREDIT_HISTORY: CodeInfo(CodeKind.POSITIVE, "Кредитная история без нарушений"),
    ReasonCode.REVENUE_STABLE_OR_GROWING: CodeInfo(
        CodeKind.POSITIVE, "Выручка стабильна или растёт"
    ),
    ReasonCode.ESTABLISHED_BUSINESS: CodeInfo(CodeKind.POSITIVE, "Бизнесу 24 месяца и больше"),
}

# client_reason_code стоп-факторов — таблица «Стоп-фактор» в design §3.4.
STOP_FACTORS: dict[StopFactor, CodeInfo] = {
    StopFactor.COMPANY_INACTIVE: CodeInfo(
        CodeKind.STOP, "Компания ликвидируется или ликвидирована", ClientReasonCode.COMPANY_STATUS
    ),
    StopFactor.APPLICANT_NOT_AUTHORIZED: CodeInfo(
        CodeKind.STOP,
        "Заявитель не руководитель по реестру",
        ClientReasonCode.APPLICANT_NOT_AUTHORIZED,
    ),
    StopFactor.BANKRUPTCY_PROCEEDING: CodeInfo(
        CodeKind.STOP, "Процедура банкротства (ФНС)", ClientReasonCode.COMPANY_STATUS
    ),
    StopFactor.ACCOUNT_BLOCKED_BY_FNS: CodeInfo(
        CodeKind.STOP,
        "Действующие блокировки счетов ФНС",
        ClientReasonCode.TAX_AUTHORITY_RESTRICTIONS,
    ),
    StopFactor.ACCOUNT_HISTORY_INSUFFICIENT: CodeInfo(
        CodeKind.STOP,
        "История по счёту меньше 6 месяцев или нулевая база выручки",
        ClientReasonCode.INSUFFICIENT_DATA,
    ),
}
