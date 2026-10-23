"""Граничные случаи ядра: строгие типы, валидация правил, хеш входов, редкие ветки."""

import dataclasses
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from app.schemas.enums import BkiSummaryStatus as Bki
from app.schemas.enums import CalculationStatus, ManagerAction
from app.schemas.enums import ReasonCode as RC
from app.scoring.categorization import RuleSet
from app.scoring.features import build_features
from app.scoring.hashing import canonical_json, inputs_hash
from app.scoring.money import DECIMAL_CONTEXT, display_dscr, money_str, round_money, to_decimal
from app.scoring.policy import allowed_actions
from app.scoring.risk import (
    ScoringInputError,
    annuity_factor,
    assess,
    limit_for_term,
    monthly_payment,
)
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


# --- issue #6: невалидные ставки и финансовые входы, включая вложенные float ---------------


@pytest.mark.parametrize("rate", [Decimal(-1), Decimal(-1200), Decimal("100.01")])
def test_invalid_rate_is_rejected(rate: Decimal) -> None:
    with pytest.raises(ScoringInputError) as exc:
        annuity_factor(rate, 12)
    assert exc.value.code == "RATE_INVALID"


@pytest.mark.parametrize("rate", ["NaN", "Infinity"])
def test_non_finite_rate_is_rejected(rate: str) -> None:
    with pytest.raises(ValueError):
        annuity_factor(Decimal(rate), 12)


def test_rate_bounds_are_inclusive() -> None:
    with localcontext(DECIMAL_CONTEXT):  # ядро считает в prec=34, а не в глобальном 28
        assert annuity_factor(Decimal(0), 12) == Decimal(1) / 12
    assert annuity_factor(Decimal(100), 12) > annuity_factor(Decimal(24), 12)


def test_invalid_product_rate_blocks_assess() -> None:
    bad = dataclasses.replace(INVESTMENT, annual_rate_pct=Decimal(-5))
    with pytest.raises(ScoringInputError, match="RATE_INVALID"):
        assess(bad, Decimal(1_000_000), 36, BAKERY, Bki.CLEAN)


@pytest.mark.parametrize(
    "call",
    [
        lambda: annuity_factor(24.0, 12),  # type: ignore[arg-type]
        lambda: monthly_payment(
            dataclasses.replace(INVESTMENT, max_amount_rub=5_000_000.0),  # type: ignore[arg-type]
            Decimal(1_000_000),
            36,
        ),
        lambda: assess(
            INVESTMENT,
            Decimal(1_000_000),
            36,
            dataclasses.replace(BAKERY, cfads_monthly_rub=240000.0),  # type: ignore[arg-type]
            Bki.CLEAN,
        ),
        lambda: limit_for_term(INVESTMENT, Decimal(1), Decimal(0), 36.0),  # type: ignore[arg-type]
        lambda: round_money(1.005),  # type: ignore[arg-type]
        lambda: display_dscr(1.2487),  # type: ignore[arg-type]
    ],
    ids=["rate", "nested-product", "nested-features", "term", "round_money", "display_dscr"],
)
def test_float_anywhere_in_input_is_type_error(call: Callable[[], object]) -> None:
    with pytest.raises(TypeError, match="float"):
        call()


def test_nested_float_in_monthly_series_is_type_error() -> None:
    point = dataclasses.replace(BAKERY.monthly[0], revenue=1.0)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match=r"monthly\[0\]"):
        assess(
            INVESTMENT,
            Decimal(1_000_000),
            36,
            dataclasses.replace(BAKERY, monthly=(point, *BAKERY.monthly[1:])),
            Bki.CLEAN,
        )


def test_negative_existing_debt_is_rejected() -> None:
    with pytest.raises(ScoringInputError, match="FEATURES_INVALID"):
        assess(INVESTMENT, Decimal(1_000_000), 36, features("240000", "-1"), Bki.CLEAN)
    with pytest.raises(ScoringInputError, match="FEATURES_INVALID"):
        limit_for_term(INVESTMENT, Decimal(240_000), Decimal(-1), 36)
