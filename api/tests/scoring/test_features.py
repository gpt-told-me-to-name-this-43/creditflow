"""FeatureBuilder: окно, h = 5/6/7/12, пустые месяцы, нулевая база, БКИ против выписки."""

from datetime import date
from decimal import Decimal

import pytest

from app.schemas.enums import CalculationStatus, StopFactor
from app.schemas.enums import TransactionCategory as C
from app.scoring.categorization import CategorizedTransaction, StatementTransaction
from app.scoring.features import build_features, full_months_between
from tests.scoring._data import AS_OF

REGISTERED = date(2020, 1, 1)


def tx(day: str, category: C, amount: int, direction: str | None = None) -> CategorizedTransaction:
    if direction is None:
        direction = "IN" if category in (C.CUSTOMER_PAYMENT, C.ACQUIRING) else "OUT"
    t = StatementTransaction(
        f"x-{day}-{category}",
        date.fromisoformat(day),
        direction,  # type: ignore[arg-type]
        Decimal(amount),
        "0099000021",
        False,
        "",
    )
    return CategorizedTransaction(t, category, "test")


def build(txs: list[CategorizedTransaction], bki: int = 0):  # type: ignore[no-untyped-def]
    return build_features(
        txs, as_of=AS_OF, registered_at=REGISTERED, bki_monthly_payments_rub=Decimal(bki)
    )


def months(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_window_is_exactly_12_full_months() -> None:
    f = build([tx(f"{m}-10", C.CUSTOMER_PAYMENT, 1000) for m in months("2025-09", "2026-10")])
    assert f.monthly[0].month == date(2025, 10, 1) and f.monthly[-1].month == date(2026, 9, 1)
    assert len(f.monthly) == 12
    # операции 2025-09 (до окна) и 2026-10 (месяц as_of) в ряд не попадают
    assert sum(p.revenue for p in f.monthly) == Decimal(12_000)
    assert f.h == 12  # первая операция раньше окна


@pytest.mark.parametrize(
    ("first", "h", "status"),
    [
        ("2026-05", 5, CalculationStatus.SKIPPED),
        ("2026-04", 6, CalculationStatus.OK),
        ("2026-03", 7, CalculationStatus.OK),
        ("2025-10", 12, CalculationStatus.OK),
    ],
)
def test_h_counts_months_from_first_operation(
    first: str, h: int, status: CalculationStatus
) -> None:
    f = build([tx(f"{m}-10", C.CUSTOMER_PAYMENT, 1000) for m in months(first, "2026-09")])
    assert (f.h, f.calculation_status) == (h, status)
    if status is CalculationStatus.SKIPPED:
        assert f.skip_reason is StopFactor.ACCOUNT_HISTORY_INSUFFICIENT
        assert f.cfads_monthly_rub is None


def test_empty_month_inside_history_does_not_shrink_h() -> None:
    # апрель–сентябрь без июня: по design h = 6 (от первой операции), а не 5 непустых месяцев
    f = build([tx(f"2026-0{m}-10", C.CUSTOMER_PAYMENT, 1000) for m in (4, 5, 7, 8, 9)])
    assert f.h == 6 and f.calculation_status is CalculationStatus.OK
    june = next(p for p in f.monthly if p.month == date(2026, 6, 1))
    assert june.revenue == 0  # пустой месяц есть в ряду нулём


def test_revenue_change_uses_k_halves() -> None:
    # h = 12, k = 6: prev6 по 1000, last6 по 920 → −8.00%
    txs = [tx(f"{m}-10", C.CUSTOMER_PAYMENT, 1000) for m in months("2025-10", "2026-03")]
    txs += [tx(f"{m}-10", C.CUSTOMER_PAYMENT, 920) for m in months("2026-04", "2026-09")]
    assert build(txs).revenue_change_pct == Decimal("-8")


def test_zero_revenue_base_is_skipped() -> None:
    txs = [tx(f"{m}-10", C.SUPPLIER, 100) for m in months("2025-10", "2026-03")]
    txs += [tx(f"{m}-10", C.CUSTOMER_PAYMENT, 1000) for m in months("2026-04", "2026-09")]
    f = build(txs)
    assert f.calculation_status is CalculationStatus.SKIPPED
    assert f.skip_reason is StopFactor.ACCOUNT_HISTORY_INSUFFICIENT


@pytest.mark.parametrize(
    ("statement", "bki", "expected"), [(5_000, 9_000, 9_000), (9_000, 5_000, 9_000)]
)
def test_existing_debt_is_max_of_last3_and_bki(statement: int, bki: int, expected: int) -> None:
    txs = [tx(f"{m}-10", C.CUSTOMER_PAYMENT, 100_000) for m in months("2025-10", "2026-09")]
    txs += [tx(f"{m}-15", C.LOAN_REPAYMENT, statement) for m in months("2026-07", "2026-09")]
    txs += [tx("2026-01-15", C.LOAN_REPAYMENT, 1_000_000)]  # вне последних 3 мес. — не учитывается
    assert build(txs, bki).existing_debt_payments_rub == Decimal(expected)


def test_cfads_is_median_of_last_6() -> None:
    nets = [238_000, 250_000, 230_000, 242_000, 235_000, 245_000]
    txs = [tx(f"{m}-10", C.CUSTOMER_PAYMENT, 1_000_000) for m in months("2025-10", "2026-09")]
    txs += [
        tx(f"{m}-12", C.SUPPLIER, 1_000_000 - n)
        for m, n in zip(months("2026-04", "2026-09"), nets, strict=True)
    ]
    assert build(txs).cfads_monthly_rub == Decimal(240_000)


def test_direction_is_checked_with_category() -> None:
    # OUT с категорией выручки не должен попасть в revenue
    txs = [tx(f"{m}-10", C.CUSTOMER_PAYMENT, 1000) for m in months("2025-10", "2026-09")]
    txs.append(tx("2026-09-11", C.CUSTOMER_PAYMENT, 5000, direction="OUT"))
    assert build(txs).monthly[-1].revenue == Decimal(1000)


def test_business_age_full_months() -> None:
    assert full_months_between(date(2023, 10, 21), AS_OF) == 36
    assert full_months_between(date(2023, 10, 22), AS_OF) == 35
