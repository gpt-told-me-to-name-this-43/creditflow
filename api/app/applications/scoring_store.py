"""Сохранение расчёта в `scoring_results` и восстановление входов для оффера (design §3.7).

`inputs_json` хранит признаки с помесячными рядами и источники решения: по ним оффер
(`kind = COUNTER_OFFER`) пересчитывается «на тех же входах», без повторного запроса ext-sim.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Application, DecisionProposal, ScoringResult
from app.schemas.enums import BkiSummaryStatus, CalculationStatus, StopFactor
from app.scoring.features import FeatureSet, MonthlyPoint
from app.scoring.hashing import inputs_hash
from app.scoring.money import money_str, round_money
from app.scoring.policy import Proposal
from app.scoring.risk import RiskResult
from app.scoring.versions import ENGINE_VERSION, POLICY_VERSION


@dataclass(frozen=True)
class ScoringInputs:
    """Всё, от чего зависит расчёт и рекомендация (кроме версий — их добавляет inputs_hash)."""

    product_id: str
    annual_rate_pct: Decimal
    amount_rub: Decimal
    term_months: int
    as_of_date: date
    features: FeatureSet
    bki_status: BkiSummaryStatus
    blocking_codes: tuple[StopFactor, ...]

    def to_json(self) -> dict[str, Any]:
        f = self.features
        return {
            "product_id": self.product_id,
            "annual_rate_pct": money_str(self.annual_rate_pct),
            "amount_rub": money_str(self.amount_rub),
            "term_months": self.term_months,
            "as_of_date": self.as_of_date.isoformat(),
            "bki_status": self.bki_status.value,
            "blocking_codes": [c.value for c in self.blocking_codes],
            "features": {
                "calculation_status": f.calculation_status.value,
                "h": f.h,
                "k": f.k,
                # точные значения, без округления: оффер пересчитывается по ним же
                "cfads_monthly_rub": _exact(f.cfads_monthly_rub),
                "revenue_change_pct": _exact(f.revenue_change_pct),
                "existing_debt_payments_rub": _exact(f.existing_debt_payments_rub),
                "business_age_months": f.business_age_months,
                "skip_reason": f.skip_reason.value if f.skip_reason else None,
                "monthly": [
                    {
                        "month": p.month.isoformat(),
                        "revenue": _exact(p.revenue),
                        "opex": _exact(p.opex),
                        "debt_svc": _exact(p.debt_svc),
                    }
                    for p in f.monthly
                ],
            },
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ScoringInputs":
        f = data["features"]
        features = FeatureSet(
            calculation_status=CalculationStatus(f["calculation_status"]),
            h=f["h"],
            k=f["k"],
            cfads_monthly_rub=_dec(f["cfads_monthly_rub"]),
            revenue_change_pct=_dec(f["revenue_change_pct"]),
            existing_debt_payments_rub=Decimal(f["existing_debt_payments_rub"]),
            business_age_months=f["business_age_months"],
            monthly=tuple(
                MonthlyPoint(
                    date.fromisoformat(p["month"]),
                    Decimal(p["revenue"]),
                    Decimal(p["opex"]),
                    Decimal(p["debt_svc"]),
                )
                for p in f["monthly"]
            ),
            skip_reason=StopFactor(f["skip_reason"]) if f["skip_reason"] else None,
        )
        return cls(
            product_id=data["product_id"],
            annual_rate_pct=Decimal(data["annual_rate_pct"]),
            amount_rub=Decimal(data["amount_rub"]),
            term_months=data["term_months"],
            as_of_date=date.fromisoformat(data["as_of_date"]),
            features=features,
            bki_status=BkiSummaryStatus(data["bki_status"]),
            blocking_codes=tuple(StopFactor(c) for c in data["blocking_codes"]),
        )


def _exact(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def add_scoring(
    session: AsyncSession,
    application_id: uuid.UUID,
    kind: str,
    inputs: ScoringInputs,
    risk: RiskResult | None,
) -> ScoringResult:
    """Новая insert-only запись расчёта. `risk is None` — SKIPPED (метрик нет)."""
    data = inputs.to_json()
    row = ScoringResult(
        id=uuid.uuid4(),
        application_id=application_id,
        kind=kind,
        inputs_json=data,
        inputs_hash=inputs_hash(data),
        engine_version=ENGINE_VERSION,
        calculation_status=(CalculationStatus.OK if risk else CalculationStatus.SKIPPED).value,
        monthly_payment_rub=risk.monthly_payment_rub if risk else None,
        dscr=risk.dscr if risk else None,
        score=risk.score if risk else None,
        factor_points_json=dict(risk.factor_points) if risk else None,
        risk_level=risk.risk_level.value if risk else None,
        reason_codes=[c.value for c in risk.reason_codes] if risk else [],
        positive_codes=[c.value for c in risk.positive_codes] if risk else [],
        limit_rub=round_money(risk.limit_rub) if risk and risk.limit_rub is not None else None,
    )
    session.add(row)
    return row


def add_proposal(
    session: AsyncSession, scoring: ScoringResult, proposal: Proposal
) -> DecisionProposal:
    row = DecisionProposal(
        id=uuid.uuid4(),
        scoring_result_id=scoring.id,
        policy_version=POLICY_VERSION,
        blocking_codes=[c.value for c in proposal.blocking_codes],
        suggested_action=proposal.suggested_action.value,
        rule_trace_json=[
            {"rule": t.rule, "matched": t.matched, "detail": t.detail} for t in proposal.rule_trace
        ],
    )
    session.add(row)
    return row


@dataclass(frozen=True)
class Current:
    """Текущий расчёт заявки и рекомендация исходного Submit (оффер рекомендации не имеет)."""

    scoring: ScoringResult
    proposal: DecisionProposal
    inputs: ScoringInputs


async def load_current(session: AsyncSession, application: Application) -> Current | None:
    if application.current_scoring_id is None:
        return None
    scoring = await session.get(ScoringResult, application.current_scoring_id)
    proposal = await session.scalar(
        select(DecisionProposal)
        .join(ScoringResult, ScoringResult.id == DecisionProposal.scoring_result_id)
        .where(ScoringResult.application_id == application.id)
        .order_by(DecisionProposal.created_at.desc())
        .limit(1)
    )
    assert scoring is not None and proposal is not None
    return Current(scoring, proposal, ScoringInputs.from_json(scoring.inputs_json))
