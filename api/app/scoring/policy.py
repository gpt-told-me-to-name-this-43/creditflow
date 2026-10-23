"""DecisionPolicy — стоп-факторы, suggested_action, allowed_actions (design.md §3.4, §3.5).

Правила R1–R5 проверяются по порядку; первое сработавшее задаёт suggested_action,
но в rule_trace пишутся ВСЕ пять правил. Политика не принимает решения: стоп-фактор
оставляет менеджеру только REJECT (автоотказа нет).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.schemas.enums import (
    BkiSummaryStatus,
    ManagerAction,
    RegistryStatus,
    StopFactor,
    SuggestedAction,
)
from app.scoring.features import FeatureSet
from app.scoring.money import exact
from app.scoring.risk import TARGET_DSCR, RiskResult

ELIGIBLE_MIN_SCORE = 80


@dataclass(frozen=True)
class RuleTrace:
    rule: str  # R1…R5
    matched: bool
    detail: str | None


@dataclass(frozen=True)
class Proposal:
    blocking_codes: tuple[StopFactor, ...]
    suggested_action: SuggestedAction
    rule_trace: tuple[RuleTrace, ...]


def stop_factors(
    *,
    registry_status: RegistryStatus,
    applicant_authorized: bool,
    bankruptcy: bool,
    active_account_blocks: int,
    features: FeatureSet,
) -> tuple[StopFactor, ...]:
    """Все сработавшие стоп-факторы в порядке таблицы design §3.4 (не только первый)."""
    found: list[StopFactor] = []
    if registry_status in (RegistryStatus.LIQUIDATING, RegistryStatus.LIQUIDATED):
        found.append(StopFactor.COMPANY_INACTIVE)
    if not applicant_authorized:
        found.append(StopFactor.APPLICANT_NOT_AUTHORIZED)
    if bankruptcy:
        found.append(StopFactor.BANKRUPTCY_PROCEEDING)
    if active_account_blocks > 0:
        found.append(StopFactor.ACCOUNT_BLOCKED_BY_FNS)
    if features.skip_reason is not None:
        found.append(features.skip_reason)
    return tuple(found)


@exact
def evaluate(
    blocking_codes: Sequence[StopFactor],
    bki_status: BkiSummaryStatus,
    risk: RiskResult | None,
) -> Proposal:
    """`risk is None` — расчёт пропущен (SKIPPED): R3/R4 не срабатывают, а не падают."""
    trace: list[RuleTrace] = []
    action: SuggestedAction | None = None

    def rule(name: str, matched: bool, outcome: SuggestedAction, detail: str | None) -> None:
        nonlocal action
        trace.append(RuleTrace(name, matched, detail))
        if matched and action is None:
            action = outcome

    rule(
        "R1",
        bool(blocking_codes),
        SuggestedAction.BLOCKED_BY_RULE,
        ",".join(blocking_codes) or None,
    )
    rule(
        "R2",
        bki_status == BkiSummaryStatus.SERIOUS,
        SuggestedAction.MANUAL_REVIEW,
        f"bki={bki_status}",
    )
    if risk is None:
        rule("R3", False, SuggestedAction.COUNTER_OFFER_CANDIDATE, "calculation=SKIPPED")
        rule("R4", False, SuggestedAction.ELIGIBLE_FOR_MANAGER_REVIEW, "calculation=SKIPPED")
    else:
        rule(
            "R3",
            risk.dscr < TARGET_DSCR and risk.limit_rub is not None,
            SuggestedAction.COUNTER_OFFER_CANDIDATE,
            f"dscr={risk.dscr} limit={risk.limit_rub}",
        )
        rule(
            "R4",
            risk.dscr >= TARGET_DSCR and risk.score >= ELIGIBLE_MIN_SCORE,
            SuggestedAction.ELIGIBLE_FOR_MANAGER_REVIEW,
            f"dscr={risk.dscr} score={risk.score}",
        )
    rule("R5", action is None, SuggestedAction.MANUAL_REVIEW, None)

    assert action is not None  # R5 срабатывает всегда, если ничего выше не сработало
    return Proposal(tuple(blocking_codes), action, tuple(trace))


def allowed_actions(
    blocking_codes: Sequence[StopFactor], limit_rub: Decimal | None
) -> tuple[ManagerAction, ...]:
    """Единственный источник истины для GET карточки и POST /decisions (design §3.5)."""
    if blocking_codes:
        return (ManagerAction.REJECT,)
    actions = [ManagerAction.APPROVE]
    if limit_rub is not None:
        actions.append(ManagerAction.COUNTER_OFFER)
    actions += [ManagerAction.REQUEST_INFO, ManagerAction.REJECT]
    return tuple(actions)
