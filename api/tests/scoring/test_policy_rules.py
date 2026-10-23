"""Табличный тест R1–R5, стоп-факторы, реестр кодов, категоризация, версии порогов."""

import hashlib
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.schemas.enums import BkiSummaryStatus as Bki
from app.schemas.enums import ReasonCode, RegistryStatus, RiskLevel, StopFactor
from app.schemas.enums import SuggestedAction as SA
from app.schemas.enums import TransactionCategory as C
from app.scoring import risk as risk_module
from app.scoring.categorization import StatementTransaction, categorize, load_rules
from app.scoring.codes import REASON_CODES, STOP_FACTORS
from app.scoring.policy import evaluate, stop_factors
from app.scoring.risk import RiskResult
from app.scoring.versions import ENGINE_VERSION
from tests.scoring._data import BAKERY

BASE = RiskResult(
    Decimal(1), Decimal(1), Decimal("1.30"), 85, {}, RiskLevel.LOW, (), (), Decimal(1_000_000)
)


@pytest.mark.parametrize(
    ("blocking", "bki", "risk", "expected"),
    [
        ([StopFactor.COMPANY_INACTIVE], Bki.SERIOUS, BASE, SA.BLOCKED_BY_RULE),  # R1 раньше R2
        ([], Bki.SERIOUS, BASE, SA.MANUAL_REVIEW),  # R2 раньше R4
        ([], Bki.CLEAN, replace(BASE, dscr=Decimal("1.2499")), SA.COUNTER_OFFER_CANDIDATE),  # R3
        ([], Bki.CLEAN, BASE, SA.ELIGIBLE_FOR_MANAGER_REVIEW),  # R4
        ([], Bki.CLEAN, replace(BASE, score=79), SA.MANUAL_REVIEW),  # R5: score < 80
        ([], Bki.CLEAN, replace(BASE, dscr=Decimal("0.9"), limit_rub=None), SA.MANUAL_REVIEW),  # R5
        ([StopFactor.ACCOUNT_HISTORY_INSUFFICIENT], Bki.CLEAN, None, SA.BLOCKED_BY_RULE),  # SKIPPED
    ],
)
def test_r1_r5(blocking: list[StopFactor], bki: Bki, risk: RiskResult | None, expected: SA) -> None:
    proposal = evaluate(blocking, bki, risk)
    assert proposal.suggested_action is expected
    assert [t.rule for t in proposal.rule_trace] == ["R1", "R2", "R3", "R4", "R5"]


def test_skipped_without_stop_factor_does_not_crash() -> None:
    assert evaluate([], Bki.CLEAN, None).suggested_action is SA.MANUAL_REVIEW


def test_all_stop_factors_collected() -> None:
    skipped = replace(BAKERY, skip_reason=StopFactor.ACCOUNT_HISTORY_INSUFFICIENT)
    found = stop_factors(
        registry_status=RegistryStatus.LIQUIDATED,
        applicant_authorized=False,
        bankruptcy=True,
        active_account_blocks=1,
        features=skipped,
    )
    assert found == tuple(StopFactor)  # все пять, в порядке таблицы design


def test_code_registry_is_complete() -> None:
    assert set(REASON_CODES) == set(ReasonCode)
    assert set(STOP_FACTORS) == set(StopFactor)
    assert all(info.client_reason_code for info in STOP_FACTORS.values())


def _tx(
    direction: str, purpose: str, inn: str | None = "0099000021", bank: bool = False
) -> StatementTransaction:
    return StatementTransaction("x", date(2026, 9, 1), direction, Decimal(1), inn, bank, purpose)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("tx", "category"),
    [
        (_tx("OUT", "Перевод", inn="0099020010"), C.OWN_TRANSFER),  # правило 1 раньше всех
        (_tx("OUT", "Погашение кредита", bank=True), C.LOAN_REPAYMENT),
        (_tx("OUT", "Уплата процентов", bank=True), C.LOAN_REPAYMENT),
        (_tx("OUT", "Погашение кредита"), C.UNCLASSIFIED),  # не банк → нет
        (_tx("IN", "Выдача кредита по дог. 1", bank=True), C.LOAN_PROCEEDS),
        (_tx("IN", "Предоставление кредита", bank=True), C.LOAN_PROCEEDS),
        (_tx("OUT", "Налог. КБК 18210501011011000110"), C.TAX),
        (_tx("OUT", "Налог. КБК 39210202010061000160"), C.UNCLASSIFIED),  # не 182
        (_tx("OUT", "Перечисление ЗАРАБОТНОЙ платы", inn=None), C.SALARY),
        (_tx("OUT", "Арендная плата за 09.2026"), C.RENT),
        (_tx("OUT", "Снятие наличных"), C.CASH_WITHDRAWAL),
        (_tx("OUT", "Перевод", inn="009902001012"), C.OWNER_TRANSFER),
        (_tx("IN", "Зачисление по операциям эквайринга", bank=True), C.ACQUIRING),
        (_tx("IN", "Оплата по счёту № 1"), C.CUSTOMER_PAYMENT),  # «ё» → «е»
        (_tx("IN", "За услуги по договору", inn="009903001040"), C.CUSTOMER_PAYMENT),  # ИП
        (_tx("IN", "Возврат по договору"), C.UNCLASSIFIED),  # IN — не выручка
        (_tx("OUT", "Оплата поставки"), C.SUPPLIER),
        (_tx("OUT", "Перевод по договору № 7-П"), C.UNCLASSIFIED),  # OUT → opex
    ],
)
def test_categorization_first_match(tx: StatementTransaction, category: C) -> None:
    (result,) = categorize(
        [tx], load_rules(), company_inn="0099020010", director_inn="009902001012"
    )
    assert result.category is category


# Отпечаток порогов RiskEngine для каждой версии. Поменяли порог/баллы — поднимите
# ENGINE_VERSION и добавьте сюда новую строку; иначе тест упадёт (критерий #6).
THRESHOLD_FINGERPRINTS = {
    "risk-1.0.0": "aee2529c4cad89ae52a8039827b0a554ed44db8e4ec9d4249d3943afcc05e62a"
}


def test_threshold_change_requires_version_bump() -> None:
    snapshot = repr(
        (
            risk_module.TARGET_DSCR,
            risk_module.LIMIT_STEP,
            risk_module.DSCR_POINTS,
            sorted(risk_module.BKI_POINTS.items()),
            risk_module.REVENUE_POINTS,
            risk_module.AGE_POINTS,
            risk_module.RISK_LEVELS,
        )
    )
    assert THRESHOLD_FINGERPRINTS[ENGINE_VERSION] == hashlib.sha256(snapshot.encode()).hexdigest()
