"""Граничные случаи ядра: строгие типы, валидация правил, хеш входов, редкие ветки."""

from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.enums import BkiSummaryStatus as Bki
from app.schemas.enums import CalculationStatus, ManagerAction
from app.schemas.enums import ReasonCode as RC
from app.scoring.categorization import RuleSet
from app.scoring.features import build_features
from app.scoring.hashing import canonical_json, inputs_hash
from app.scoring.money import money_str, to_decimal
from app.scoring.policy import allowed_actions
from app.scoring.risk import ScoringInputError, annuity_factor, assess, monthly_payment
from tests.scoring._data import AS_OF, BAKERY, INVESTMENT, features


@pytest.mark.parametrize("value", [1.5, True])
def test_to_decimal_rejects_float_and_bool(value: object) -> None:
    with pytest.raises(TypeError):
        to_decimal(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["NaN", "Infinity"])
def test_to_decimal_rejects_non_finite(value: str) -> None:
    with pytest.raises(ValueError):
        to_decimal(value)


def test_money_str_format() -> None:
    assert money_str(Decimal("117698.555")) == "117698.56"
    assert money_str(Decimal(5)) == "5.00"


def test_inputs_hash_is_canonical() -> None:
    a = {"amount": Decimal("100.00"), "b": [Bki.CLEAN, AS_OF]}
    b = {"b": [Bki.CLEAN, AS_OF], "amount": Decimal(100)}  # другой порядок ключей и масштаб
    assert canonical_json(a) == canonical_json(b)
    assert inputs_hash(a) == inputs_hash(b)
    assert inputs_hash(a) != inputs_hash({**a, "amount": Decimal(101)})
    assert '"cfads_monthly_rub":"240000"' in canonical_json(BAKERY)  # dataclass → dict


@pytest.mark.parametrize("bad", [1.5, object()])
def test_inputs_hash_rejects_unknown_types(bad: object) -> None:
    with pytest.raises(TypeError):
        inputs_hash({"x": bad})


@pytest.mark.parametrize(
    "rules",
    [
        [{"id": "a", "category": "TAX", "when": {"purpose_regex": "("}}],  # невалидный regex
        [{"id": "a", "category": "TAX", "when": {}}, {"id": "a", "category": "RENT", "when": {}}],
        [{"id": "a", "category": "NOPE", "when": {}}],  # неизвестная категория
        [{"id": "a", "category": "TAX", "when": {"typo": 1}}],  # лишнее поле
    ],
)
def test_invalid_rules_fail_validation(rules: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        RuleSet.model_validate({"version": "v", "rules": rules})


def test_no_transactions_is_skipped() -> None:
    f = build_features([], as_of=AS_OF, registered_at=AS_OF, bki_monthly_payments_rub=Decimal(0))
    assert (f.h, f.calculation_status) == (0, CalculationStatus.SKIPPED)


def test_allowed_actions_with_limit() -> None:
    assert allowed_actions([], Decimal(1)) == (
        ManagerAction.APPROVE,
        ManagerAction.COUNTER_OFFER,
        ManagerAction.REQUEST_INFO,
        ManagerAction.REJECT,
    )


def test_term_must_be_int_and_positive() -> None:
    with pytest.raises(TypeError):
        monthly_payment(INVESTMENT, Decimal(1_000_000), True)
    with pytest.raises(ScoringInputError):
        annuity_factor(Decimal(24), 0)


def test_assess_refuses_skipped_features() -> None:
    skipped = replace(BAKERY, calculation_status=CalculationStatus.SKIPPED, cfads_monthly_rub=None)
    with pytest.raises(ScoringInputError, match="CALCULATION_SKIPPED"):
        assess(INVESTMENT, Decimal(1_000_000), 36, skipped, Bki.CLEAN)


def test_sharp_decline_and_young_business_codes() -> None:
    r = assess(INVESTMENT, Decimal(1_000_000), 36, features("400000", "0", "-15.01", 11), Bki.MINOR)
    assert r.factor_points == {"dscr": 40, "bki": 10, "revenue": 0, "age": 0}
    assert r.reason_codes == (RC.CREDIT_HISTORY_MINOR, RC.REVENUE_SHARP_DECLINE, RC.YOUNG_BUSINESS)
    assert r.positive_codes == (RC.DSCR_MEETS_TARGET,)
    # граница [−15; 0): ровно −15 — ещё 8 баллов
    edge_features = features("400000", "0", "-15", 12)
    edge = assess(INVESTMENT, Decimal(1_000_000), 36, edge_features, Bki.UNKNOWN)
    assert edge.factor_points["revenue"] == 8 and edge.factor_points["age"] == 8
