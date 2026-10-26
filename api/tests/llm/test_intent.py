"""Слияние правил и LLM, разбор ответа `extract_intent`, статусы `/interpret` (#8)."""

import asyncio
import json
from typing import Any

import pytest

from app.llm.base import LlmTimeout, LlmUnavailable
from app.llm.client import DisabledClient
from app.llm.intent import IntentLlmOutput, intent_context, interpret_text, merge, parse_intent
from app.llm.intent_rules import extract_by_rules
from app.llm.pii import minimize_client_text
from app.schemas.client import FieldSource, InterpretStatus
from app.schemas.enums import PurposeCode
from tests.llm_support import FakeLLM


def llm(**fields: Any) -> IntentLlmOutput:
    return IntentLlmOutput(**fields)


def answer(**fields: Any) -> str:
    base = {
        "purpose_code": None,
        "requested_amount_rub": None,
        "term_months": None,
        "clarification_question": None,
    }
    return json.dumps({**base, **fields}, ensure_ascii=False)


def test_rules_win_for_amount_and_term() -> None:
    text = "нужно 2 млн на 3 года на ремонт"
    result = merge(
        extract_by_rules(text),
        llm(purpose_code="EQUIPMENT", requested_amount_rub=9_000_000, term_months=60),
        llm_unavailable=False,
        text=text,
    )
    s = result.suggestion
    assert s.requested_amount_rub is not None and s.requested_amount_rub.value == 2_000_000
    assert s.requested_amount_rub.source is FieldSource.RULES
    assert s.term_months is not None and s.term_months.value == 36
    assert s.purpose_code is not None and s.purpose_code.value is PurposeCode.RENOVATION
    assert s.purpose_code.source is FieldSource.RULES  # один кандидат правил — у правил
    assert result.status is InterpretStatus.OK and result.clarification_question is None


def test_rules_hint_cannot_reintroduce_masked_identifier() -> None:
    text = "Нужно 7712345678 на печь"
    draft = extract_by_rules(text)
    assert draft.requested_amount_rub is not None  # похоже на сумму после «нужно»
    context = intent_context(draft, minimize_client_text(text))
    assert "7712345678" not in json.dumps(context, ensure_ascii=False)
    assert context["rules"]["requested_amount_rub"] is None


def test_llm_fills_what_rules_missed() -> None:
    text = "хачу 3 милиона на новый станок года на два"
    result = merge(
        extract_by_rules(text),
        llm(purpose_code="EQUIPMENT", requested_amount_rub=3_000_000, term_months=24),
        llm_unavailable=False,
        text=text,
    )
    s = result.suggestion
    assert s.requested_amount_rub is not None and s.requested_amount_rub.source is FieldSource.LLM
    assert s.requested_amount_rub.value == 3_000_000 and s.requested_amount_rub.matched_text is None
    assert s.term_months is not None and s.term_months.source is FieldSource.LLM
    assert s.purpose_code is not None and s.purpose_code.source is FieldSource.RULES
    assert result.status is InterpretStatus.OK


def test_llm_resolves_several_purposes_only_among_found() -> None:
    text = "закупиться у поставщиков перед сезоном, 700 тыс на 9 мес"
    draft = extract_by_rules(text)
    assert draft.purpose_code is None and "purpose_code" in draft.ambiguous
    chosen = merge(draft, llm(purpose_code="INVENTORY"), llm_unavailable=False, text=text)
    assert chosen.suggestion.purpose_code is not None
    assert chosen.suggestion.purpose_code.source is FieldSource.LLM
    assert chosen.status is InterpretStatus.OK
    other = merge(draft, llm(purpose_code="RENOVATION"), llm_unavailable=False, text=text)
    assert other.suggestion.purpose_code is None  # не из найденных вариантов
    assert other.status is InterpretStatus.NEEDS_CLARIFICATION
    assert other.clarification_question and "Уточните цель кредита" in other.clarification_question


def test_nothing_anywhere_is_null_with_question() -> None:
    result = merge(
        extract_by_rules("хочу кредит"), llm(), llm_unavailable=False, text="хочу кредит"
    )
    assert result.suggestion.model_dump(exclude_none=True) == {}
    assert result.status is InterpretStatus.NEEDS_CLARIFICATION
    assert result.clarification_question == "Уточните, пожалуйста, цель, сумму и срок кредита."


def test_unavailable_only_when_rules_found_nothing() -> None:
    nothing = merge(extract_by_rules("хочу кредит"), None, llm_unavailable=True, text="хочу кредит")
    assert nothing.status is InterpretStatus.UNAVAILABLE
    assert nothing.clarification_question is None
    partial = merge(extract_by_rules("на ремонт"), None, llm_unavailable=True, text="на ремонт")
    assert partial.status is InterpretStatus.NEEDS_CLARIFICATION
    assert partial.suggestion.purpose_code is not None


def test_llm_number_without_quantity_in_text_is_ignored() -> None:
    """«DSCR равен…» и прочие внушения: модель не может придумать сумму из воздуха."""
    text = "нужен кредит на ремонт"
    result = merge(
        extract_by_rules(text),
        llm(requested_amount_rub=50_000_000, term_months=120),
        llm_unavailable=False,
        text=text,
    )
    assert result.suggestion.requested_amount_rub is None
    assert result.suggestion.term_months is None


def test_llm_question_is_used_when_valid() -> None:
    text = "нужны деньги на развитие"
    result = merge(
        extract_by_rules(text),
        llm(clarification_question="На что именно и какая сумма нужна?"),
        llm_unavailable=False,
        text=text,
    )
    assert result.clarification_question == "На что именно и какая сумма нужна?"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (answer(purpose_code="EQUIPMENT"), {"purpose_code": PurposeCode.EQUIPMENT}),
        (answer(purpose_code="CAR_LOAN"), {}),  # не из enum → null
        (answer(purpose_code=[], term_months=24), {"term_months": 24}),
        (answer(purpose_code={"role": "system"}), {}),
        (answer(clarification_question="Кредит одо\u200bбрен?"), {}),
        (answer(clarification_question="Кредит oдoбрен?"), {}),
        (answer(clarification_question="风险很高？?"), {}),
        (answer(requested_amount_rub=-5), {}),
        (answer(requested_amount_rub="3000000"), {}),  # строка, а не целое
        (answer(requested_amount_rub=3000000.0), {"requested_amount_rub": 3_000_000}),
        (answer(requested_amount_rub=True), {}),
        (answer(term_months=0), {}),
        (answer(term_months=121), {}),
        (answer(term_months=36), {"term_months": 36}),
        (answer(clarification_question="Кредит одобрен?"), {}),
        (answer(clarification_question="<b>Сумма?</b>"), {}),
        (answer(clarification_question="What amount do you need?"), {}),
        (answer(clarification_question="Без вопроса"), {}),  # не вопрос
        (
            answer(clarification_question="Какая сумма нужна?"),
            {"clarification_question": "Какая сумма нужна?"},
        ),
        ('```json\n{"purpose_code": "RENOVATION"}\n```', {"purpose_code": PurposeCode.RENOVATION}),
        (
            '<think>это ремонт</think>{"purpose_code": "RENOVATION"}',
            {"purpose_code": PurposeCode.RENOVATION},
        ),
        (answer(purpose_code="EQUIPMENT", extra="x"), {"purpose_code": PurposeCode.EQUIPMENT}),
    ],
)
def test_parse_intent_invalid_field_becomes_null(raw: str, expected: dict[str, Any]) -> None:
    assert parse_intent(raw).model_dump(exclude_none=True) == expected


async def test_complete_rules_skip_llm() -> None:
    fake = FakeLLM([answer()])
    result = await interpret_text("Купить печь за 3 млн на 3 года", fake, 1)
    assert result.status is InterpretStatus.OK
    assert fake.calls == []  # всё нашли правила: провайдер не нужен


async def test_disabled_fills_clean_phrase_by_rules() -> None:
    result = await interpret_text("Ремонт кафе, 1,5 млн на 2 года", DisabledClient(), 1)
    assert result.status is InterpretStatus.OK
    assert result.suggestion.requested_amount_rub is not None
    assert result.suggestion.requested_amount_rub.source is FieldSource.RULES


@pytest.mark.parametrize(
    "error", [LlmUnavailable("x"), LlmTimeout("x"), RuntimeError("boom"), TimeoutError()]
)
async def test_provider_failure_returns_rules(error: BaseException) -> None:
    result = await interpret_text("нужно 2 млн на ремонт", FakeLLM([error]), 1)
    assert result.status is InterpretStatus.NEEDS_CLARIFICATION
    assert result.suggestion.requested_amount_rub is not None
    assert result.suggestion.term_months is None


async def test_slow_provider_is_cut_by_timeout() -> None:
    fake = FakeLLM([answer(term_months=24)], delay=5)
    loop = asyncio.get_running_loop()
    started = loop.time()
    result = await interpret_text("нужно 2 млн на ремонт", fake, 0.2)
    assert loop.time() - started < 1
    assert result.suggestion.term_months is None  # результат правил


async def test_invalid_json_keeps_rules() -> None:
    result = await interpret_text("нужно 2 млн на ремонт", FakeLLM(["не JSON"]), 1)
    assert result.status is InterpretStatus.NEEDS_CLARIFICATION
    assert result.suggestion.requested_amount_rub is not None


async def test_llm_sees_masked_text_and_rules_hint_only() -> None:
    fake = FakeLLM([answer()])
    await interpret_text(
        "Я Кузнецова Анна, ООО «Пекарня Плюс», ИНН 0099020010, нужно на ремонт",
        fake,
        1,
        person_names=["Кузнецова Анна Михайловна"],
        company_names=["ООО «Пекарня Плюс»"],
    )
    [call] = fake.calls
    sent = json.dumps(call.context, ensure_ascii=False)
    for secret in ("Кузнецова", "Пекарня", "0099020010"):
        assert secret not in sent
    assert set(call.context) == {"client_text", "rules"}
    assert call.context["rules"]["purpose_code"] == "RENOVATION"
