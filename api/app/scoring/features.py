"""FeatureBuilder — признаки выписки (design.md §3.4). Чистая функция на Decimal.

Окно — ровно 12 полных календарных месяцев ДО месяца as_of_date
(для 2026-10-21 → 2025-10-01 … 2026-09-30). Все 12 месяцев присутствуют в ряду,
пустые — нулями: ряд идёт на график менеджера, а медиана и k считаются по месяцам,
а не по «месяцам, где что-то было».

  h  = месяцев от первой операции (вообще, не только в окне) до конца окна, ≤ 12
  k  = ⌊h/2⌋
  cfads_monthly_rub          = median(revenue − opex) за последние min(6, h) мес.
  revenue_change_pct         = (Σ revenue[последние k] / Σ revenue[предыдущие k] − 1) · 100
  existing_debt_payments_rub = max(mean(debt_svc) за последние 3 мес., БКИ)
  business_age_months        = полные месяцы от регистрации до as_of_date

h < 6 или Σ revenue[предыдущие k] = 0 → SKIPPED + ACCOUNT_HISTORY_INSUFFICIENT.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.schemas.enums import CalculationStatus, StopFactor
from app.schemas.enums import TransactionCategory as C
from app.scoring.categorization import CategorizedTransaction
from app.scoring.money import ZERO, exact, to_decimal

REVENUE = frozenset({C.CUSTOMER_PAYMENT, C.ACQUIRING})
OPEX = frozenset(
    {C.SUPPLIER, C.SALARY, C.TAX, C.RENT, C.CASH_WITHDRAWAL, C.OWNER_TRANSFER, C.UNCLASSIFIED}
)
DEBT_SVC = frozenset({C.LOAN_REPAYMENT})
WINDOW_MONTHS = 12
MIN_HISTORY_MONTHS = 6
CFADS_MONTHS = 6
DEBT_MONTHS = 3


@dataclass(frozen=True)
class MonthlyPoint:
    month: date  # первое число месяца
    revenue: Decimal
    opex: Decimal
    debt_svc: Decimal


@dataclass(frozen=True)
class FeatureSet:
    calculation_status: CalculationStatus
    h: int
    k: int
    cfads_monthly_rub: Decimal | None  # None при SKIPPED
    revenue_change_pct: Decimal | None  # None при SKIPPED
    existing_debt_payments_rub: Decimal
    business_age_months: int
    monthly: tuple[MonthlyPoint, ...]  # всегда 12 точек, старые → новые
    skip_reason: StopFactor | None = None


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def _from_index(i: int) -> date:
    return date(i // 12, i % 12 + 1, 1)


def full_months_between(start: date, end: date) -> int:
    """Полные месяцы: 2023-10-21 → 2026-10-21 = 36; 2023-10-22 → 2026-10-21 = 35."""
    months = _month_index(end) - _month_index(start)
    return months - 1 if end.day < start.day else months


def _median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


@exact
def build_features(
    transactions: Sequence[CategorizedTransaction],
    *,
    as_of: date,
    registered_at: date,
    bki_monthly_payments_rub: Decimal,
) -> FeatureSet:
    window_end = _month_index(as_of)  # месяц as_of НЕ входит в окно
    window_start = window_end - WINDOW_MONTHS
    totals = {
        i: {"revenue": ZERO, "opex": ZERO, "debt": ZERO} for i in range(window_start, window_end)
    }

    for ct in transactions:
        i = _month_index(ct.tx.booked_at)
        if i not in totals:
            continue
        amount = to_decimal(ct.tx.amount_rub)
        # направление проверяется явно: категория сама по себе не гарантирует IN/OUT
        if ct.category in REVENUE and ct.tx.direction == "IN":
            totals[i]["revenue"] += amount
        elif ct.category in OPEX and ct.tx.direction == "OUT":
            totals[i]["opex"] += amount
        elif ct.category in DEBT_SVC and ct.tx.direction == "OUT":
            totals[i]["debt"] += amount

    monthly = tuple(
        MonthlyPoint(_from_index(i), t["revenue"], t["opex"], t["debt"])
        for i, t in sorted(totals.items())
    )

    # h — от первой операции вообще: операция до окна значит h = 12
    if transactions:
        first = min(_month_index(ct.tx.booked_at) for ct in transactions)
        h = max(0, min(WINDOW_MONTHS, window_end - first))
    else:
        h = 0
    k = h // 2

    debt_tail = [p.debt_svc for p in monthly[-DEBT_MONTHS:]]
    existing_debt = max(sum(debt_tail, ZERO) / DEBT_MONTHS, to_decimal(bki_monthly_payments_rub))
    age = full_months_between(registered_at, as_of)

    def skipped() -> FeatureSet:
        return FeatureSet(
            CalculationStatus.SKIPPED,
            h,
            k,
            None,
            None,
            existing_debt,
            age,
            monthly,
            StopFactor.ACCOUNT_HISTORY_INSUFFICIENT,
        )

    if h < MIN_HISTORY_MONTHS:
        return skipped()

    active = monthly[-h:]
    revenue = [p.revenue for p in active]
    base = sum(revenue[-2 * k : -k], ZERO)
    if base == 0:
        return skipped()
    recent = sum(revenue[-k:], ZERO)

    return FeatureSet(
        calculation_status=CalculationStatus.OK,
        h=h,
        k=k,
        cfads_monthly_rub=_median([p.revenue - p.opex for p in active[-min(CFADS_MONTHS, h) :]]),
        revenue_change_pct=(recent / base - 1) * 100,
        existing_debt_payments_rub=existing_debt,
        business_age_months=age,
        monthly=monthly,
    )
