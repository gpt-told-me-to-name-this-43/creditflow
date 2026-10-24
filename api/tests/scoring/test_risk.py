"""M1–M7, M9, M10, M12, M13 (design.md §5). Эталоны — литералы из спецификации."""

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.enums import BkiSummaryStatus as Bki
from app.schemas.enums import ReasonCode as RC
from app.schemas.enums import RiskLevel, SuggestedAction
from app.scoring.money import display_dscr, round_money
from app.scoring.policy import allowed_actions, evaluate
from app.scoring.risk import (
    ScoringInputError,
    annuity_factor,
    assess,
    limit_for_term,
    monthly_payment,
)
from app.scoring.schedule import build_schedule
from tests.scoring._data import BAKERY, INVESTMENT, ZERO_RATE, features


def test_m1_bakery_requested_terms() -> None:
    r = assess(INVESTMENT, Decimal(3_000_000), 36, BAKERY, Bki.CLEAN)
    assert r.monthly_payment_rub == Decimal("117698.56")
    assert Decimal("1.10244") <= r.dscr < Decimal("1.10245")
    assert display_dscr(r.dscr) == Decimal("1.10")
    assert r.score == 63 and r.risk_level is RiskLevel.MODERATE
    assert r.factor_points == {"dscr": 10, "bki": 30, "revenue": 8, "age": 15}
    assert r.limit_rub == Decimal("2340000")
    assert r.reason_codes == (RC.DSCR_BELOW_TARGET, RC.REVENUE_DECLINE)
    assert r.positive_codes == (RC.CLEAN_CREDIT_HISTORY, RC.ESTABLISHED_BUSINESS)
    assert evaluate([], Bki.CLEAN, r).suggested_action is SuggestedAction.COUNTER_OFFER_CANDIDATE


def test_m2_threshold_is_compared_unrounded() -> None:
    r = assess(INVESTMENT, Decimal(2_350_000), 36, BAKERY, Bki.CLEAN)
    assert Decimal("1.24871") <= r.dscr < Decimal("1.24872")
    assert r.dscr < Decimal("1.25")  # не проходит, хотя HALF_UP дал бы 1.25
    assert display_dscr(r.dscr) == Decimal("1.24")
    assert r.factor_points["dscr"] == 10


def test_m3_bakery_at_limit_is_eligible() -> None:
    r = assess(INVESTMENT, Decimal(2_340_000), 36, BAKERY, Bki.CLEAN)
    assert r.monthly_payment_rub == Decimal("91804.88")
    assert Decimal("1.25127") <= r.dscr < Decimal("1.25128")
    assert r.factor_points["dscr"] == 30
    assert r.score == 83 and r.risk_level is RiskLevel.LOW
    assert (
        evaluate([], Bki.CLEAN, r).suggested_action is SuggestedAction.ELIGIBLE_FOR_MANAGER_REVIEW
    )


def test_m4_dscr_exactly_target_passes() -> None:
    r = assess(ZERO_RATE, Decimal(1_200_000), 12, features("125000", "0"), Bki.CLEAN)
    assert r.monthly_payment_rub == Decimal("100000.00")
    assert r.dscr == Decimal("1.25")
    assert r.factor_points["dscr"] == 30  # ≥ 1.25 включительно


def test_m5_just_below_target_fails() -> None:
    r = assess(ZERO_RATE, Decimal(1_200_012), 12, features("125000", "0"), Bki.CLEAN)
    assert Decimal("1.2499875") <= r.dscr < Decimal("1.2499876")  # M5: 1.2499875…
    assert r.dscr < Decimal("1.25")
    assert display_dscr(r.dscr) == Decimal("1.24")


def test_m6_payment_round_half_up() -> None:
    p = monthly_payment(ZERO_RATE, Decimal(100_001), 8)
    assert p == Decimal("12500.125")
    assert round_money(p) == Decimal("12500.13")


def test_m7_high_debt_load_manual_review() -> None:
    r = assess(INVESTMENT, Decimal(1_000_000), 36, features("120000", "100000", "0", 36), Bki.CLEAN)
    assert Decimal("0.86186") <= r.dscr < Decimal("0.86187")
    assert r.score == 60
    assert r.risk_level is RiskLevel.HIGH  # 60 = MODERATE, но DSCR < 1 → не ниже HIGH
    assert r.limit_rub is None
    proposal = evaluate([], Bki.CLEAN, r)
    assert proposal.suggested_action is SuggestedAction.MANUAL_REVIEW
    assert [t.rule for t in proposal.rule_trace if t.matched] == ["R5"]


@pytest.mark.parametrize(
    ("amount", "term", "error"),
    [
        (Decimal(0), 36, ScoringInputError),
        (Decimal(-1), 36, ScoringInputError),
        (Decimal("1000000.5"), 36, ScoringInputError),
        (Decimal(99_999), 36, ScoringInputError),  # ниже min продукта
        (Decimal(5_000_001), 36, ScoringInputError),  # выше max продукта
        (Decimal(1_000_000), 11, ScoringInputError),  # срок вне продукта
        (Decimal(1_000_000), 61, ScoringInputError),
        (1_000_000.0, 36, TypeError),  # float запрещён
        (Decimal(1_000_000), 36.0, TypeError),
    ],
)
def test_m9_invalid_input(amount: object, term: object, error: type[Exception]) -> None:
    with pytest.raises(error):
        monthly_payment(INVESTMENT, amount, term)  # type: ignore[arg-type]


def test_m9_scoring_error_is_value_error_with_code() -> None:
    with pytest.raises(ValueError) as exc:
        monthly_payment(INVESTMENT, Decimal(0), 36)
    assert isinstance(exc.value, ScoringInputError) and exc.value.code == "AMOUNT_INVALID"


@pytest.mark.parametrize(
    ("term", "limit"),
    [
        (36, Decimal(2_340_000)),
        (48, Decimal(2_820_000)),
        (60, Decimal(3_190_000)),
        (61, None),
        (11, None),
    ],
)
def test_m10_limit_for_term(term: int, limit: Decimal | None) -> None:
    assert limit_for_term(INVESTMENT, Decimal(240_000), Decimal(100_000), term) == limit


def test_limit_capped_by_product_max_and_floored_to_10k() -> None:
    # огромный cfads → упираемся в max_amount
    assert limit_for_term(INVESTMENT, Decimal(10_000_000), Decimal(0), 36) == Decimal(5_000_000)
    limit = limit_for_term(INVESTMENT, Decimal(123_457), Decimal(0), 24)
    assert limit is not None and limit % 10_000 == 0


def test_limit_below_product_min_is_none() -> None:
    # P_max = 4 000 → ~75 тыс. на 24 мес. < min 100 000
    assert limit_for_term(INVESTMENT, Decimal(5_000), Decimal(0), 24) is None


def test_zero_rate_and_single_month() -> None:
    assert annuity_factor(Decimal(0), 1) == 1
    assert monthly_payment(ZERO_RATE, Decimal(1_000), 1) == Decimal(1_000)


def test_unknown_bki_status_rejected() -> None:
    with pytest.raises(ValueError):
        assess(INVESTMENT, Decimal(1_000_000), 36, BAKERY, "GARBAGE")  # type: ignore[arg-type]


def test_reject_only_when_blocked() -> None:
    assert [a.value for a in allowed_actions(["COMPANY_INACTIVE"], Decimal(1))] == ["REJECT"]  # type: ignore[list-item]
    assert [a.value for a in allowed_actions([], None)] == ["APPROVE", "REQUEST_INFO", "REJECT"]


def test_m12_schedule() -> None:
    rows = build_schedule(Decimal(2_340_000), Decimal(24), 36, date(2026, 10, 21))
    assert all(r.payment_rub == Decimal("91804.88") for r in rows[:35])
    assert rows[-1].payment_rub == Decimal("91804.63")
    assert sum(r.interest_rub for r in rows) == Decimal("964975.43")
    assert sum(r.principal_rub for r in rows) == Decimal("2340000.00")
    assert rows[-1].balance_after_rub == 0


def test_m13_schedule_zero_rate_end_of_month() -> None:
    (row,) = build_schedule(Decimal(500_000), Decimal(0), 1, date(2027, 1, 31))
    assert row.payment_rub == Decimal("500000.00")
    assert row.due_date == date(2027, 2, 28)
