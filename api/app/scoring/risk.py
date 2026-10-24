"""RiskEngine — платёж, DSCR, лимит, scorecard, risk level, коды (design.md §3.4).

  r = rate / 1200;  A(r, n) = 1/n при r = 0, иначе r / (1 − (1 + r)^−n);  P = S · A(r, n)
  DSCR  = cfads / (existing_debt + P)
  P_max = max(0, cfads / 1.25 − existing_debt)          — не зависит от срока
  limit_for_term(t) = ⌊min(P_max / A(r, t), max_amount) / 10 000⌋ · 10 000,
                      None, если результат < min_amount или t вне [min_term, max_term]

Все пороги — по неокруглённым P и DSCR; округляются только хранимый платёж (HALF_UP)
и показываемый DSCR (DOWN). Движок не знает о стоп-факторах и действиях менеджера.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.schemas.enums import BkiSummaryStatus, CalculationStatus, ReasonCode, RiskLevel
from app.scoring.features import FeatureSet
from app.scoring.money import ZERO, exact, floor_to, round_money, to_decimal

TARGET_DSCR = Decimal("1.25")
LIMIT_STEP = Decimal("10000")

# (порог включительно, баллы) — сверху вниз; последний порог «иначе».
DSCR_POINTS = ((Decimal("1.50"), 40), (Decimal("1.25"), 30), (Decimal("1.00"), 10))
BKI_POINTS = {
    BkiSummaryStatus.CLEAN: 30,
    BkiSummaryStatus.UNKNOWN: 15,
    BkiSummaryStatus.MINOR: 10,
    BkiSummaryStatus.SERIOUS: 0,
}
REVENUE_POINTS = ((Decimal("0"), 15), (Decimal("-15"), 8))  # ≥ 0 → 15; [−15; 0) → 8; иначе 0
AGE_POINTS = ((24, 15), (12, 8))  # ≥ 24 → 15; 12–23 → 8; < 12 → 0
RISK_LEVELS = ((80, RiskLevel.LOW), (60, RiskLevel.MODERATE), (40, RiskLevel.HIGH))


class ScoringInputError(ValueError):
    """Невалидный вход движка: нарушен инвариант, который API обязан проверить раньше.

    `code` — внутренний машинный код для логов и тестов (`AMOUNT_OUT_OF_PRODUCT`, `RATE_INVALID`…),
    а не член `ErrorCode`: наружу такая ошибка уходит как 422 `VALIDATION_ERROR` (#7).
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True)
class Product:
    id: str
    annual_rate_pct: Decimal
    min_amount_rub: Decimal
    max_amount_rub: Decimal
    min_term_months: int
    max_term_months: int


@dataclass(frozen=True)
class RiskResult:
    monthly_payment_raw: Decimal  # неокруглённый P — от него считаются DSCR и пороги
    monthly_payment_rub: Decimal  # хранится и показывается (ROUND_HALF_UP)
    dscr: Decimal  # неокруглённый; для показа — display_dscr()
    score: int
    factor_points: dict[str, int]
    risk_level: RiskLevel
    reason_codes: tuple[ReasonCode, ...]
    positive_codes: tuple[ReasonCode, ...]
    limit_rub: Decimal | None  # limit_for_term на запрошенном сроке


def _validate_term(product: Product, term: int) -> None:
    if isinstance(term, bool) or not isinstance(term, int):
        raise TypeError("term_months должен быть int")
    if not product.min_term_months <= term <= product.max_term_months:
        raise ScoringInputError("TERM_OUT_OF_PRODUCT", f"срок {term} вне продукта {product.id}")


def _validate_amount(product: Product, amount: Decimal) -> Decimal:
    value = to_decimal(amount)  # float/bool → TypeError
    if value <= 0 or value != value.to_integral_value():
        raise ScoringInputError("AMOUNT_INVALID", "сумма — целые рубли больше нуля")
    if not product.min_amount_rub <= value <= product.max_amount_rub:
        raise ScoringInputError("AMOUNT_OUT_OF_PRODUCT", f"сумма вне продукта {product.id}")
    return value


MAX_ANNUAL_RATE_PCT = Decimal(100)


def _validate_rate(annual_rate_pct: Decimal) -> Decimal:
    """Ставка в процентах годовых, 0 ≤ rate ≤ 100. Отрицательная ставка даёт платёж меньше
    S/n, а −1200% — деление на ноль в формуле аннуитета; в каталоге (design §3.3) — 24%."""
    rate = to_decimal(annual_rate_pct)  # float/bool → TypeError, NaN/Infinity → ValueError
    if not ZERO <= rate <= MAX_ANNUAL_RATE_PCT:
        raise ScoringInputError("RATE_INVALID", f"ставка {rate}% вне [0; 100]")
    return rate


def _validate_debt(existing_debt: Decimal) -> Decimal:
    """Отрицательный текущий долг завысил бы DSCR и лимит."""
    debt = to_decimal(existing_debt)
    if debt < 0:
        raise ScoringInputError("FEATURES_INVALID", "existing_debt_payments_rub < 0")
    return debt


@exact
def annuity_factor(annual_rate_pct: Decimal, term: int) -> Decimal:
    if isinstance(term, bool) or not isinstance(term, int):
        raise TypeError("term_months должен быть int")
    if term < 1:
        raise ScoringInputError("TERM_OUT_OF_PRODUCT", "срок должен быть ≥ 1")
    r = _validate_rate(annual_rate_pct) / 1200
    if r == 0:
        return Decimal(1) / term
    return r / (1 - (1 + r) ** -term)


@exact
def monthly_payment(product: Product, amount: Decimal, term: int) -> Decimal:
    """Неокруглённый аннуитетный платёж; при 0% — ровно S/n."""
    _validate_term(product, term)
    return _validate_amount(product, amount) * annuity_factor(product.annual_rate_pct, term)


@exact
def limit_for_term(
    product: Product, cfads: Decimal, existing_debt: Decimal, term: int
) -> Decimal | None:
    """Максимальная сумма на сроке `term`, при которой DSCR ≥ 1.25. Нужна и для оффера (#7)."""
    if not product.min_term_months <= term <= product.max_term_months:
        return None
    p_max = max(ZERO, to_decimal(cfads) / TARGET_DSCR - _validate_debt(existing_debt))
    raw = min(p_max / annuity_factor(product.annual_rate_pct, term), product.max_amount_rub)
    limit = floor_to(raw, LIMIT_STEP)
    return limit if limit >= product.min_amount_rub else None


def _points(
    value: Decimal | int, table: tuple[tuple[Decimal, int], ...] | tuple[tuple[int, int], ...]
) -> int:
    for threshold, points in table:
        if value >= threshold:
            return points
    return 0


@exact
def assess(
    product: Product,
    amount: Decimal,
    term: int,
    features: FeatureSet,
    bki_status: BkiSummaryStatus,
) -> RiskResult:
    """Полный расчёт на запрошенных условиях. При SKIPPED-признаках вызывать нельзя."""
    if (
        features.calculation_status is not CalculationStatus.OK
        or features.cfads_monthly_rub is None
    ):
        raise ScoringInputError("CALCULATION_SKIPPED", "признаков недостаточно, расчёт пропущен")
    assert features.revenue_change_pct is not None
    bki = BkiSummaryStatus(bki_status)  # неизвестный статус → ValueError, а не 0 баллов

    payment = monthly_payment(product, amount, term)
    cfads = to_decimal(features.cfads_monthly_rub)  # может быть < 0 (убыток) — это не ошибка
    debt = _validate_debt(features.existing_debt_payments_rub)
    dscr = cfads / (debt + payment)  # payment > 0 после валидации → знаменатель > 0

    points = {
        "dscr": _points(dscr, DSCR_POINTS),
        "bki": BKI_POINTS[bki],
        "revenue": _points(features.revenue_change_pct, REVENUE_POINTS),
        "age": _points(features.business_age_months, AGE_POINTS),
    }
    score = sum(points.values())
    level = next((lvl for floor, lvl in RISK_LEVELS if score >= floor), RiskLevel.VERY_HIGH)
    if dscr < 1 and level in (RiskLevel.LOW, RiskLevel.MODERATE):
        level = RiskLevel.HIGH  # при DSCR < 1.00 уровень не ниже HIGH

    risk: list[ReasonCode] = []
    plus: list[ReasonCode] = []
    if dscr < 1:
        risk.append(ReasonCode.DSCR_BELOW_ONE)
    elif dscr < TARGET_DSCR:
        risk.append(ReasonCode.DSCR_BELOW_TARGET)
    else:
        plus.append(ReasonCode.DSCR_MEETS_TARGET)
    bki_code = {
        BkiSummaryStatus.SERIOUS: ReasonCode.CREDIT_HISTORY_SERIOUS,
        BkiSummaryStatus.MINOR: ReasonCode.CREDIT_HISTORY_MINOR,
        BkiSummaryStatus.UNKNOWN: ReasonCode.CREDIT_HISTORY_UNKNOWN,
    }.get(bki)
    if bki_code is None:
        plus.append(ReasonCode.CLEAN_CREDIT_HISTORY)
    else:
        risk.append(bki_code)
    if features.revenue_change_pct < -15:
        risk.append(ReasonCode.REVENUE_SHARP_DECLINE)
    elif features.revenue_change_pct < 0:
        risk.append(ReasonCode.REVENUE_DECLINE)
    else:
        plus.append(ReasonCode.REVENUE_STABLE_OR_GROWING)
    # Порог YOUNG_BUSINESS в design явно не задан; берём границу полного балла (24 мес.)
    # и фиксируем её в codes.py / docs/demo-data.md.
    if features.business_age_months < 24:
        risk.append(ReasonCode.YOUNG_BUSINESS)
    else:
        plus.append(ReasonCode.ESTABLISHED_BUSINESS)

    return RiskResult(
        monthly_payment_raw=payment,
        monthly_payment_rub=round_money(payment),
        dscr=dscr,
        score=score,
        factor_points=points,
        risk_level=level,
        reason_codes=tuple(risk),
        positive_codes=tuple(plus),
        limit_rub=limit_for_term(product, cfads, debt, term),
    )
