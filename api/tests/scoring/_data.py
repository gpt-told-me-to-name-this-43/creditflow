"""Общие входы unit-тестов ядра. Эталоны — литералы из design.md §5 (M1–M13), не вывод кода."""

from datetime import date
from decimal import Decimal

from app.schemas.enums import CalculationStatus
from app.scoring.features import FeatureSet, MonthlyPoint
from app.scoring.risk import Product

AS_OF = date(2026, 10, 21)

# Каталог из design §3.3. В проде продукты приходят из credit_products (seed).
INVESTMENT = Product("investment", Decimal(24), Decimal(100_000), Decimal(5_000_000), 12, 60)
WORKING_CAPITAL = Product(
    "working_capital", Decimal(25), Decimal(100_000), Decimal(3_000_000), 3, 24
)
# Для M4–M6: ставка 0% и широкие пределы, чтобы проверить ровно формулу.
ZERO_RATE = Product("zero", Decimal(0), Decimal(1), Decimal(10_000_000), 1, 60)


def features(cfads: str, debt: str, revenue_change_pct: str = "0", age: int = 36) -> FeatureSet:
    """Готовые признаки — для тестов RiskEngine без выписки."""
    empty = tuple(
        MonthlyPoint(date(2026, m, 1), Decimal(0), Decimal(0), Decimal(0)) for m in range(1, 13)
    )
    return FeatureSet(
        calculation_status=CalculationStatus.OK,
        h=12,
        k=6,
        cfads_monthly_rub=Decimal(cfads),
        revenue_change_pct=Decimal(revenue_change_pct),
        existing_debt_payments_rub=Decimal(debt),
        business_age_months=age,
        monthly=empty,
    )


BAKERY = features("240000", "100000", "-8", 36)  # «Пекарня Плюс»
