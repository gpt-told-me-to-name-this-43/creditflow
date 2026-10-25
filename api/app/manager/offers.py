"""Проверка встречного предложения — одна функция для `offer-preview` и `decisions` (design §3.5).

Оффер меняет сумму и/или срок в пределах продукта; продукт и ставка прежние. Сумма не
больше `limit_for_term(срок)`; если срок не менялся, сумма меньше запрошенной. Расчёт —
на тех же входах, что и исходный (признаки из `scoring_results.inputs_json`).
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from app.applications.catalog import CatalogProduct
from app.applications.scoring_store import ScoringInputs
from app.core.errors import AppError
from app.schemas.common import ErrorCode, ValidationDetail, ValidationDetails
from app.schemas.enums import CalculationStatus, ManagerAction
from app.schemas.manager import (
    CalculatedOfferPreview,
    OfferPreviewResponse,
    OfferViolation,
    SkippedOfferPreview,
)
from app.scoring.money import display_dscr, money_str
from app.scoring.policy import allowed_actions
from app.scoring.risk import RiskResult, assess, limit_for_term

V = OfferViolation


@dataclass(frozen=True)
class OfferCheck:
    amount: Decimal
    term: int
    violations: tuple[OfferViolation, ...]
    risk: RiskResult | None  # None — условия невычислимы (SKIPPED или вне продукта)
    limit_for_term: Decimal | None
    inputs: ScoringInputs  # входы расчёта оффера: исходные с новыми суммой и сроком

    @property
    def valid(self) -> bool:
        return not self.violations


def check_offer(
    inputs: ScoringInputs,
    product: CatalogProduct,
    current_limit: Decimal | None,
    amount_rub: int | None,
    term_months: int | None,
) -> OfferCheck:
    amount = Decimal(amount_rub) if amount_rub is not None else inputs.amount_rub
    term = term_months if term_months is not None else inputs.term_months
    offer_inputs = replace(inputs, amount_rub=amount, term_months=term)
    violations: list[OfferViolation] = []
    if ManagerAction.COUNTER_OFFER not in allowed_actions(inputs.blocking_codes, current_limit):
        violations.append(V.ACTION_NOT_ALLOWED)
    features = inputs.features
    if features.calculation_status is CalculationStatus.SKIPPED:
        violations.append(V.CALCULATION_SKIPPED)
        return OfferCheck(amount, term, tuple(violations), None, None, offer_inputs)
    if not product.min_term_months <= term <= product.max_term_months:
        violations.append(V.TERM_OUT_OF_PRODUCT)
    if not product.min_amount_rub <= amount <= product.max_amount_rub:
        violations.append(V.AMOUNT_OUT_OF_PRODUCT)
    if V.TERM_OUT_OF_PRODUCT in violations or V.AMOUNT_OUT_OF_PRODUCT in violations:
        return OfferCheck(amount, term, tuple(violations), None, None, offer_inputs)

    assert features.cfads_monthly_rub is not None
    risk = assess(product.risk, amount, term, features, inputs.bki_status)
    limit = limit_for_term(
        product.risk, features.cfads_monthly_rub, features.existing_debt_payments_rub, term
    )
    if limit is None or amount > limit:
        violations.append(V.AMOUNT_ABOVE_LIMIT)
    if term == inputs.term_months and amount >= inputs.amount_rub:
        violations.append(V.OFFER_NOT_IMPROVED)
    return OfferCheck(amount, term, tuple(violations), risk, limit, offer_inputs)


def preview(check: OfferCheck) -> OfferPreviewResponse:
    if check.risk is None:
        return SkippedOfferPreview(
            calculation_status=CalculationStatus.SKIPPED,
            monthly_payment_rub=None,
            dscr=None,
            score=None,
            risk_level=None,
            limit_for_term_rub=None,
            valid=False,
            violations=list(check.violations),
        )
    return CalculatedOfferPreview(
        calculation_status=CalculationStatus.OK,
        monthly_payment_rub=money_str(check.risk.monthly_payment_rub),
        dscr=str(display_dscr(check.risk.dscr)),
        score=check.risk.score,
        risk_level=check.risk.risk_level,
        limit_for_term_rub=(
            money_str(check.limit_for_term) if check.limit_for_term is not None else None
        ),
        valid=check.valid,
        violations=list(check.violations),
    )


def _field_error(field: str, code: OfferViolation, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        message,
        ValidationDetails(fields=[ValidationDetail(field=field, code=code.value, message=message)]),
    )


def raise_for_decision(check: OfferCheck) -> None:
    """Те же нарушения, что в preview, — ошибкой POST /decisions (в порядке приоритета)."""
    found = set(check.violations)
    if found & {V.ACTION_NOT_ALLOWED, V.CALCULATION_SKIPPED}:
        raise AppError(ErrorCode.ACTION_NOT_ALLOWED, "Встречное предложение недоступно")
    if V.TERM_OUT_OF_PRODUCT in found:
        raise _field_error("body.term_months", V.TERM_OUT_OF_PRODUCT, "Срок вне пределов продукта")
    if V.AMOUNT_OUT_OF_PRODUCT in found:
        raise _field_error(
            "body.amount_rub", V.AMOUNT_OUT_OF_PRODUCT, "Сумма вне пределов продукта"
        )
    if V.AMOUNT_ABOVE_LIMIT in found:
        raise AppError(ErrorCode.AMOUNT_ABOVE_LIMIT, "Сумма превышает лимит на этот срок")
    if V.OFFER_NOT_IMPROVED in found:
        raise _field_error(
            "body.amount_rub",
            V.OFFER_NOT_IMPROVED,
            "При прежнем сроке сумма должна быть меньше запрошенной",
        )
