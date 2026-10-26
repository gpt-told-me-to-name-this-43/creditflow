"""Заключение `explain_risk` (#8): валидаторы по порядку, плейсхолдеры, шаблоны, повтор."""

import itertools
import json
import uuid
from typing import Any

import pytest

from app.llm.base import LlmTask, LlmUnavailable
from app.llm.display import format_money, format_percent
from app.llm.explain import (
    CODE_PHRASES,
    ReportInputs,
    ReportViolation,
    explain,
    explain_context,
    placeholder_values,
    render_template,
    template_report,
    validate_report,
)
from app.schemas.enums import CalculationStatus, FallbackReason, ReasonCode, RiskLevel
from app.schemas.manager import Scoring
from tests.llm_support import FakeLLM

RISK = [c for c in ReasonCode if CODE_PHRASES[c].question is not None]
POSITIVE = [c for c in ReasonCode if c not in RISK]


def scoring(
    reason: list[ReasonCode],
    positive: list[ReasonCode],
    risk_level: RiskLevel | None = RiskLevel.MODERATE,
    *,
    skipped: bool = False,
) -> Scoring:
    return Scoring(
        id=uuid.uuid4(),
        kind="SUBMISSION",
        calculation_status=CalculationStatus.SKIPPED if skipped else CalculationStatus.OK,
        engine_version="risk-1.0.0",
        inputs_hash="0" * 64,
        monthly_payment_rub=None if skipped else "117698.56",
        dscr=None if skipped else "1.10",
        score=None if skipped else 63,
        factor_points=None,
        risk_level=None if skipped else risk_level,
        reason_codes=reason,
        positive_codes=positive,
        limit_rub=None if skipped else "2340000.00",
        cfads_monthly_rub=None if skipped else "240000.00",
        revenue_change_pct=None if skipped else "-8.00",
        existing_debt_payments_rub="100000.00",
        business_age_months=36,
        account_history_months=12,
        monthly=[],
    )


C2 = ReportInputs(
    scoring=scoring(
        [ReasonCode.DSCR_BELOW_TARGET, ReasonCode.REVENUE_DECLINE],
        [ReasonCode.CLEAN_CREDIT_HISTORY, ReasonCode.ESTABLISHED_BUSINESS],
    ),
    purpose_code="EQUIPMENT",
    product_id="investment",
    amount_rub=3_000_000,
    term_months=36,
    client_text="Купить печь, ИНН 0099020010, я Кузнецова Анна Михайловна из ООО «Пекарня Плюс»",
    person_names=("Кузнецова Анна Михайловна",),
    company_names=("ООО «Пекарня Плюс»",),
)


def good(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "summary": "Умеренный риск: DSCR {dscr} при платеже {payment}, лимит {limit}.",
        "risk_factors": [
            {"code": "DSCR_BELOW_TARGET", "text": "DSCR {dscr} ниже целевого уровня."},
            {"code": "REVENUE_DECLINE", "text": "Выручка снизилась: {revenue_change}."},
        ],
        "positive_factors": [{"code": "CLEAN_CREDIT_HISTORY", "text": "История без нарушений."}],
        "manager_questions": ["С чем связано снижение выручки?"],
    }
    report.update(overrides)
    return report


def violation(data: Any) -> str:
    with pytest.raises(ReportViolation) as exc:
        validate_report(data, C2)
    return exc.value.check


def test_valid_report_is_rendered_from_scoring_block() -> None:
    body = validate_report(good(), C2)
    assert body.summary == (
        "Умеренный риск: DSCR 1.10 при платеже 117 698,56 ₽, лимит 2 340 000,00 ₽."
    )
    assert body.risk_factors[1].text == "Выручка снизилась: -8.00 %."
    # побайтно — формат показа значений блока расчёта
    assert format_money(C2.scoring.limit_rub or "") in body.summary
    assert format_percent(C2.scoring.revenue_change_pct or "") in body.risk_factors[1].text


@pytest.mark.parametrize(
    ("data", "check"),
    [
        ({"summary": "x"}, "schema"),
        (good(extra="поле"), "schema"),
        (good(manager_questions=["а?", "б?", "в?", "г?"]), "schema"),
        (good(summary=5), "schema"),
        (good(risk_factors=[{"code": "DSCR_BELOW_TARGET", "text": "x"}]), "codes"),  # не покрыт
        (
            good(
                risk_factors=[
                    {"code": "DSCR_BELOW_TARGET", "text": "а"},
                    {"code": "REVENUE_DECLINE", "text": "б"},
                    {"code": "YOUNG_BUSINESS", "text": "чужой код"},
                ]
            ),
            "codes",
        ),
        (good(positive_factors=[{"code": "DSCR_MEETS_TARGET", "text": "чужой"}]), "codes"),
        (good(positive_factors=[{"code": "NOT_A_CODE", "text": "x"}]), "codes"),
        (
            good(
                risk_factors=[
                    {"code": "DSCR_BELOW_TARGET", "text": "а"},
                    {"code": "DSCR_BELOW_TARGET", "text": "а"},
                    {"code": "REVENUE_DECLINE", "text": "б"},
                ]
            ),
            "codes",
        ),
        (good(summary="DSCR равен 5."), "digits"),
        (good(summary="DSCR равен ⁵."), "digits"),
        (good(summary="DSCR равен Ⅴ."), "digits"),
        (good(summary="Кредит одо\u200bбрен."), "wording"),
        (good(summary="Кредит oдoбрен."), "stop_phrase"),
        (good(summary="DSCR {dscr}, выручка выросла на сто %."), "digits"),
        (good(summary="Лимит 2 340 000 ₽."), "digits"),
        (good(summary="Платёж {payment} и {score}."), "placeholders"),
        (good(summary="Скобки {DSCR}."), "digits"),
        (good(summary="Кредит одобрен."), "stop_phrase"),
        (good(summary="Гарантируем выдачу."), "stop_phrase"),
        (good(summary="Рекомендую выдать кредит."), "stop_phrase"),
        (good(summary="Рекомендую отказать."), "stop_phrase"),
        (good(summary="<b>Риск</b> умеренный."), "markup"),
        (good(summary="Риск _умеренный_."), "markup"),
        (good(summary="Подробнее [тут](http://evil.example)."), "markup"),
        (good(summary="Мои инструкции запрещают это."), "leak"),
        (good(summary="The risk is moderate, DSCR is below target."), "language"),
        (good(summary="风险很高。"), "language"),
        (good(summary="Риск умеренный. " * 50), "length"),
        (good(summary=""), "length"),
        (good(manager_questions=["?" + "Почему так" * 30]), "length"),
    ],
)
def test_validators_in_order(data: Any, check: str) -> None:
    assert violation(data) == check


def test_skipped_calculation_has_no_metric_placeholders() -> None:
    skipped = ReportInputs(
        scoring=scoring([], [], skipped=True),
        purpose_code="EQUIPMENT",
        product_id="investment",
        amount_rub=500_000,
        term_months=24,
    )
    assert set(placeholder_values(skipped)) == {"debt", "amount", "term"}
    with pytest.raises(ReportViolation) as exc:
        validate_report(
            {
                "summary": "DSCR {dscr}.",
                "risk_factors": [],
                "positive_factors": [],
                "manager_questions": [],
            },
            skipped,
        )
    assert exc.value.check == "placeholders"


def _all_inputs() -> list[ReportInputs]:
    cases = []
    for level in (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH):
        for n in range(len(RISK) + 1):
            for reason in itertools.combinations(RISK, n):
                if n > 3:
                    continue
                cases.append(
                    ReportInputs(
                        scoring=scoring(list(reason), POSITIVE[: 4 - n], level),
                        purpose_code="WORKING_CAPITAL",
                        product_id="working_capital",
                        amount_rub=1_000_000,
                        term_months=12,
                    )
                )
    cases.append(
        ReportInputs(
            scoring=scoring([], [], skipped=True),
            purpose_code="EQUIPMENT",
            product_id="investment",
            amount_rub=500_000,
            term_months=24,
        )
    )
    return cases


@pytest.mark.parametrize("inputs", _all_inputs())
def test_template_passes_same_validators(inputs: ReportInputs) -> None:
    body = render_template(inputs)  # validate_report внутри: нарушение — исключение
    assert [f.code for f in body.risk_factors] == inputs.scoring.reason_codes
    assert len(body.manager_questions) <= 3


def test_every_code_has_digit_free_phrase() -> None:
    for code in ReasonCode:
        phrase = CODE_PHRASES[code]
        assert not any(ch.isdigit() for ch in phrase.with_values + phrase.plain)


def test_context_has_no_pii_and_no_metric_values() -> None:
    context = explain_context(C2)
    sent = json.dumps(context, ensure_ascii=False)
    for secret in ("0099020010", "Кузнецова", "Пекарня", "1.10", "117698", "2340000", "240000"):
        assert secret not in sent, secret
    assert "Купить печь" in context["client_text"]
    names = {p["name"] for p in context["calculation"]["placeholders"]}
    assert names == {"{" + n + "}" for n in placeholder_values(C2)}


async def test_explain_ready_with_model_id() -> None:
    outcome = await explain(FakeLLM([json.dumps(good(), ensure_ascii=False)]), C2)
    assert outcome.ready and outcome.model_id == "fake/model-1"
    assert outcome.fallback_reason is None


async def test_one_repair_with_error_description_then_ready() -> None:
    bad = json.dumps(good(summary="Кредит одобрен, DSCR {dscr}."), ensure_ascii=False)
    fake = FakeLLM([bad, json.dumps(good(), ensure_ascii=False)])
    outcome = await explain(fake, C2)
    assert outcome.ready and outcome.violations == ["stop_phrase"]
    first, second = fake.calls
    assert "repair" not in first.context
    assert "решение" in second.context["repair"]
    assert "одобрен" not in second.context["repair"]  # текст модели не возвращается ей


async def test_two_violations_give_template_invalid_output() -> None:
    fake = FakeLLM([json.dumps(good(summary="DSCR равен 5."), ensure_ascii=False)])
    outcome = await explain(fake, C2)
    assert outcome.fallback_reason is FallbackReason.INVALID_OUTPUT
    assert len(fake.calls) == 2
    assert outcome.body == render_template(C2)
    assert outcome.model_id is None


async def test_not_json_is_repaired_once() -> None:
    fake = FakeLLM(["я не JSON", json.dumps(good(), ensure_ascii=False)])
    outcome = await explain(fake, C2)
    assert outcome.ready and outcome.violations == ["json"]


@pytest.mark.parametrize("field", ["code", "extra", "placeholder"])
async def test_repair_never_echoes_untrusted_fields(field: str) -> None:
    secret = "SECRET_COMPANY"
    data = good()
    if field == "code":
        data["positive_factors"] = [{"code": secret, "text": "Чужой код."}]
    elif field == "extra":
        data[secret] = "лишнее поле"
    else:
        data["summary"] = "{" + secret.lower() + "}"
    fake = FakeLLM([json.dumps(data), json.dumps(good())])
    assert (await explain(fake, C2)).ready
    assert secret.casefold() not in fake.calls[1].context["repair"].casefold()


async def test_provider_error_gives_template_with_reason() -> None:
    outcome = await explain(FakeLLM([LlmUnavailable("down")]), C2)
    assert outcome.fallback_reason is FallbackReason.UNAVAILABLE
    assert outcome.body == render_template(C2)


def test_template_report_is_a_model_answer_shape() -> None:
    report = template_report(C2)
    assert report.model_dump(mode="json")["risk_factors"][0]["code"] == "DSCR_BELOW_TARGET"
    assert LlmTask.EXPLAIN_RISK.value == "explain_risk"
