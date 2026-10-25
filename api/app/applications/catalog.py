"""Каталог продуктов и подбор (design.md §3.3 «Выбор продукта»).

Продукт подходит, если цель входит в `allowed_purposes`, а сумма и срок — в его пределы;
незаданный фильтр не проверяется. Одна и та же функция `unmet_constraints` служит
`GET /credit-products`, отображению черновика и (#7, Submit) проверке `PRODUCT_NOT_ELIGIBLE`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CreditProduct as CreditProductRow
from app.schemas.client import CreditProduct
from app.schemas.common import ProductConstraint
from app.schemas.enums import PurposeCode
from app.scoring.money import money_str
from app.scoring.risk import Product as RiskProduct
from app.scoring.risk import monthly_payment
from app.seed import ProductRow


@dataclass(frozen=True)
class CatalogProduct:
    id: str
    name: str
    allowed_purposes: tuple[PurposeCode, ...]
    min_amount_rub: Decimal
    max_amount_rub: Decimal
    min_term_months: int
    max_term_months: int
    annual_rate_pct: Decimal

    @classmethod
    def from_row(cls, row: CreditProductRow) -> "CatalogProduct":
        return cls(
            row.id,
            row.name,
            tuple(PurposeCode(p) for p in row.allowed_purposes),
            row.min_amount_rub,
            row.max_amount_rub,
            row.min_term_months,
            row.max_term_months,
            row.annual_rate_pct,
        )

    @classmethod
    def from_seed(cls, row: ProductRow) -> "CatalogProduct":
        return cls(
            row["id"],
            row["name"],
            tuple(row["allowed_purposes"]),
            row["min_amount_rub"],
            row["max_amount_rub"],
            row["min_term_months"],
            row["max_term_months"],
            row["annual_rate_pct"],
        )

    @property
    def risk(self) -> RiskProduct:
        return RiskProduct(
            self.id,
            self.annual_rate_pct,
            self.min_amount_rub,
            self.max_amount_rub,
            self.min_term_months,
            self.max_term_months,
        )


async def load_catalog(session: AsyncSession) -> list[CatalogProduct]:
    rows = await session.scalars(select(CreditProductRow).order_by(CreditProductRow.id))
    return [CatalogProduct.from_row(row) for row in rows]


def unmet_constraints(
    product: CatalogProduct,
    purpose: PurposeCode | None,
    amount: int | Decimal | None,
    term: int | None,
) -> list[ProductConstraint]:
    unmet = []
    if purpose is not None and purpose not in product.allowed_purposes:
        unmet.append(ProductConstraint.PURPOSE_NOT_ALLOWED)
    if amount is not None and amount < product.min_amount_rub:
        unmet.append(ProductConstraint.AMOUNT_BELOW_PRODUCT_MIN)
    if amount is not None and amount > product.max_amount_rub:
        unmet.append(ProductConstraint.AMOUNT_ABOVE_PRODUCT_MAX)
    if term is not None and term < product.min_term_months:
        unmet.append(ProductConstraint.TERM_BELOW_PRODUCT_MIN)
    if term is not None and term > product.max_term_months:
        unmet.append(ProductConstraint.TERM_ABOVE_PRODUCT_MAX)
    return unmet


def match_products(
    catalog: Sequence[CatalogProduct],
    purpose: PurposeCode | None,
    amount: int | None,
    term: int | None,
) -> list[CreditProduct]:
    """Все продукты каталога; платёж — только у подходящего при заданных сумме и сроке."""
    result = []
    for p in catalog:
        unmet = unmet_constraints(p, purpose, amount, term)
        payment = None
        if not unmet and amount is not None and term is not None:
            payment = money_str(monthly_payment(p.risk, Decimal(amount), term))
        result.append(
            CreditProduct(
                id=p.id,
                name=p.name,
                allowed_purposes=list(p.allowed_purposes),
                min_amount_rub=money_str(p.min_amount_rub),
                max_amount_rub=money_str(p.max_amount_rub),
                min_term_months=p.min_term_months,
                max_term_months=p.max_term_months,
                annual_rate_pct=money_str(p.annual_rate_pct),
                suitable=not unmet,
                monthly_payment_rub=payment,
                unmet_constraints=unmet,
            )
        )
    return result
