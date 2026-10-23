"""Golden C1–C7: закоммиченные фикстуры ext-sim → категоризация → FeatureBuilder →
RiskEngine → DecisionPolicy. Ожидаемое — из таблицы демо-компаний issue #6 /
docs/demo-data.md, посчитано независимо от кода (вручную по формулам design §3.4).

Тест ловит расхождение генератора и ядра: если gen_statements.py даст медиану 241 000
вместо 240 000, упадёт C2, а не только «математика на литералах».
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.schemas.enums import BkiSummaryStatus, ManagerAction, RegistryStatus, RiskLevel, StopFactor
from app.schemas.enums import SuggestedAction as SA
from app.scoring.categorization import StatementTransaction, categorize, load_rules
from app.scoring.features import build_features
from app.scoring.money import display_dscr
from app.scoring.policy import allowed_actions, evaluate, stop_factors
from app.scoring.risk import Product, assess
from tests.scoring._data import AS_OF, INVESTMENT, WORKING_CAPITAL

FIXTURES = Path(__file__).resolve().parents[3] / "ext-sim" / "fixtures"


@dataclass(frozen=True)
class Golden:
    code: str
    company: str  # фрагмент названия/ФИО в реестре: ИНН задаёт генератор, тест от него не зависит
    product: Product
    amount: int
    term: int
    action: SA
    blocking: tuple[StopFactor, ...] = ()
    score: int | None = None
    dscr_display: str | None = None
    risk_level: RiskLevel | None = None
    limit: int | None = None
    cfads: str | None = None
    revenue_change_pct: str | None = None
    debt: str | None = None


CASES = [
    Golden(
        "C1",
        "ТехСервис",
        INVESTMENT,
        2_000_000,
        36,
        SA.ELIGIBLE_FOR_MANAGER_REVIEW,
        score=100,
        dscr_display="3.11",
        risk_level=RiskLevel.LOW,
        limit=5_000_000,
        cfads="400000",
        revenue_change_pct="5",
        debt="50000",
    ),
    Golden(
        "C2",
        "Пекарня Плюс",
        INVESTMENT,
        3_000_000,
        36,
        SA.COUNTER_OFFER_CANDIDATE,
        score=63,
        dscr_display="1.10",
        risk_level=RiskLevel.MODERATE,
        limit=2_340_000,
        cfads="240000",
        revenue_change_pct="-8",
        debt="100000",
    ),
    # P = 800 000 · A(2%, 12) = 75 647,68 → DSCR 3.9657…; P_max = 240 000 → 2 538 08x → 2 530 000
    Golden(
        "C3",
        "Соколова",
        WORKING_CAPITAL,
        800_000,
        12,
        SA.MANUAL_REVIEW,
        score=70,
        dscr_display="3.96",
        risk_level=RiskLevel.MODERATE,
        limit=2_530_000,
        cfads="300000",
        revenue_change_pct="3",
        debt="0",
    ),
    Golden(
        "C4",
        "Новый Старт",
        INVESTMENT,
        500_000,
        24,
        SA.BLOCKED_BY_RULE,
        blocking=(StopFactor.ACCOUNT_HISTORY_INSUFFICIENT,),
    ),
    Golden(
        "C5",
        "Вектор",
        WORKING_CAPITAL,
        1_000_000,
        12,
        SA.BLOCKED_BY_RULE,
        blocking=(StopFactor.COMPANY_INACTIVE,),
    ),
    Golden(
        "C6",
        "Склад-М",
        WORKING_CAPITAL,
        1_500_000,
        18,
        SA.BLOCKED_BY_RULE,
        blocking=(StopFactor.ACCOUNT_BLOCKED_BY_FNS,),
    ),
    Golden(
        "C7",
        "Орлов",
        INVESTMENT,
        1_000_000,
        36,
        SA.MANUAL_REVIEW,
        score=60,
        dscr_display="0.86",
        risk_level=RiskLevel.HIGH,
        limit=None,
        cfads="120000",
        revenue_change_pct="0",
        debt="100000",
    ),
]


def find_inn(company: str) -> str:
    """ИНН демо-компании по названию (ЕГРЮЛ) или ФИО ИП (ЕГРИП) в фикстурах ext-sim."""
    found = [
        path.parent.name
        for path in FIXTURES.glob("*/egr*.json")
        if company in path.read_text(encoding="utf-8")
    ]
    assert len(found) == 1, (
        f"{company}: ожидалась ровно одна компания в ext-sim/fixtures, найдено {found}"
    )
    return found[0]


def _read(inn: str, name: str) -> dict[str, Any] | None:
    path = FIXTURES / inn / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.code)
def test_golden(case: Golden) -> None:
    inn = find_inn(case.company)
    registry = _read(inn, "egrul") or _read(inn, "egrip")
    fns, bki, statement = (
        _read(inn, "fns"),
        _read(inn, "bki"),
        _read(inn, "statement"),
    )
    assert registry and fns and bki and statement, f"{case.code}: нет фикстур"
    director_inn = registry["director"]["inn"] if "director" in registry else registry["inn"]

    txs = [
        StatementTransaction(
            external_id=t["external_id"],
            booked_at=date.fromisoformat(t["booked_at"]),
            direction=t["direction"],
            amount_rub=Decimal(t["amount_rub"]),
            counterparty_inn=t["counterparty"]["inn"],
            counterparty_is_bank=t["counterparty"]["is_bank"],
            purpose=t["purpose"],
        )
        for t in statement["transactions"]
    ]
    categorized = categorize(txs, load_rules(), company_inn=inn, director_inn=director_inn)
    features = build_features(
        categorized,
        as_of=AS_OF,
        registered_at=date.fromisoformat(registry["registered_at"]),
        bki_monthly_payments_rub=Decimal(bki["monthly_payments_total_rub"]),
    )
    blocking = stop_factors(
        registry_status=RegistryStatus(registry["status"]),
        applicant_authorized=True,  # сверка руководителя — в #5/#7, здесь не проверяется
        bankruptcy=fns["bankruptcy"],
        active_account_blocks=fns["active_account_blocks"],
        features=features,
    )
    bki_status = BkiSummaryStatus(bki["summary_status"])
    risk = (
        None
        if features.skip_reason
        else assess(case.product, Decimal(case.amount), case.term, features, bki_status)
    )
    proposal = evaluate(blocking, bki_status, risk)

    assert proposal.suggested_action is case.action
    assert proposal.blocking_codes == case.blocking
    assert [t.rule for t in proposal.rule_trace] == ["R1", "R2", "R3", "R4", "R5"]
    if case.blocking:
        assert allowed_actions(blocking, risk.limit_rub if risk else None) == (
            ManagerAction.REJECT,
        )
    if case.score is not None:
        assert risk is not None
        assert features.cfads_monthly_rub == Decimal(case.cfads or "")
        assert features.revenue_change_pct == Decimal(case.revenue_change_pct or "")
        assert features.existing_debt_payments_rub == Decimal(case.debt or "")
        assert risk.score == case.score
        assert display_dscr(risk.dscr) == Decimal(case.dscr_display or "")
        assert risk.risk_level is case.risk_level
        assert risk.limit_rub == (None if case.limit is None else Decimal(case.limit))


def test_m8_bakery_short_history_is_insufficient() -> None:
    """M8, вторая часть: та же выписка, но только последние 5 месяцев → h = 5 → стоп-фактор."""
    bakery = find_inn("Пекарня Плюс")
    statement = _read(bakery, "statement")
    assert statement
    txs = [
        StatementTransaction(
            t["external_id"],
            date.fromisoformat(t["booked_at"]),
            t["direction"],
            Decimal(t["amount_rub"]),
            t["counterparty"]["inn"],
            t["counterparty"]["is_bank"],
            t["purpose"],
        )
        for t in statement["transactions"]
        if t["booked_at"] >= "2026-05-01"
    ]
    f = build_features(
        categorize(txs, load_rules(), company_inn=bakery, director_inn=None),
        as_of=AS_OF,
        registered_at=date(2023, 10, 21),
        bki_monthly_payments_rub=Decimal(100_000),
    )
    assert f.h == 5 and f.skip_reason is StopFactor.ACCOUNT_HISTORY_INSUFFICIENT
