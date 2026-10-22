import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "api"))

from app.scoring.policy import DecisionPolicy
from app.scoring.risk import RiskEngine

# Инициализация движка: ставка 24%, макс 5 млн, мин 100 тыс (из design.md)
ENGINE = RiskEngine(rate_pct=Decimal(24), max_amount=Decimal(5000000), min_amount=Decimal(100000))
POLICY = DecisionPolicy()


def check_c1():
    cfads = Decimal(400000)
    debt = Decimal(50000)
    A = ENGINE.calculate_annuity_factor(36)
    P = ENGINE.calculate_payment(Decimal(2000000), 36)
    dscr = ENGINE.calculate_dscr(cfads, debt, P)
    score = ENGINE.calculate_score(dscr, "CLEAN", Decimal(5), 60)
    limit = ENGINE.calculate_limit(cfads, debt, A)

    assert score["score"] == 100, f"C1 score: {score['score']}"
    assert score["risk_level"] == "LOW", f"C1 risk: {score['risk_level']}"
    assert dscr >= Decimal("3.11") and dscr < Decimal("3.12"), f"C1 DSCR: {dscr}"
    assert limit == Decimal(5000000), f"C1 limit: {limit}"

    decision = POLICY.evaluate([], "CLEAN", dscr, limit, score["score"])
    assert decision["suggested_action"] == "ELIGIBLE_FOR_MANAGER_REVIEW"
    print("[OK] C1: ELIGIBLE, score 100, DSCR 3.11, limit 5 000 000")


def check_c2():
    cfads = Decimal(240000)
    debt = Decimal(100000)
    A = ENGINE.calculate_annuity_factor(36)
    P = ENGINE.calculate_payment(Decimal(3000000), 36)
    dscr = ENGINE.calculate_dscr(cfads, debt, P)
    score = ENGINE.calculate_score(dscr, "CLEAN", Decimal(-8), 36)
    limit = ENGINE.calculate_limit(cfads, debt, A)

    assert P.quantize(Decimal("0.01")) == Decimal("117698.56"), (
    f"C2 P: {P.quantize(Decimal('0.01'))}")
    assert dscr >= Decimal("1.10") and dscr < Decimal("1.11"), f"C2 DSCR: {dscr}"
    assert score["score"] == 63, f"C2 score: {score['score']}"
    assert score["risk_level"] == "MODERATE", f"C2 risk: {score['risk_level']}"
    assert limit == Decimal(2340000), f"C2 limit: {limit}"

    decision = POLICY.evaluate([], "CLEAN", dscr, limit, score["score"])
    assert decision["suggested_action"] == "COUNTER_OFFER_CANDIDATE"
    print("[OK] C2: COUNTER_OFFER, score 63, DSCR 1.10, limit 2 340 000")


def check_c7():
    cfads = Decimal(120000)
    debt = Decimal(100000)
    A = ENGINE.calculate_annuity_factor(36)
    P = ENGINE.calculate_payment(Decimal(1000000), 36)
    dscr = ENGINE.calculate_dscr(cfads, debt, P)
    score = ENGINE.calculate_score(dscr, "CLEAN", Decimal(0), 36)
    limit = ENGINE.calculate_limit(cfads, debt, A)

    assert dscr >= Decimal("0.86") and dscr < Decimal("0.87"), f"C7 DSCR: {dscr}"
    assert score["score"] == 60, f"C7 score: {score['score']}"
    assert score["risk_level"] == "HIGH", (
    f"C7 risk: {score['risk_level']} (DSCR < 1.00 forces HIGH)")
    assert limit is None, f"C7 limit: {limit}"

    decision = POLICY.evaluate([], "CLEAN", dscr, limit, score["score"])
    assert decision["suggested_action"] == "MANUAL_REVIEW"
    print("[OK] C7: MANUAL_REVIEW (R5), score 60, HIGH, limit null")


if __name__ == "__main__":
    check_c1()
    check_c2()
    check_c7()
    print("\nВсё ок и т.д.")
