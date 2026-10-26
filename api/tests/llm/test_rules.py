"""`extract_by_rules` (#8): таблица примеров issue, нормализация, неоднозначности, скорость."""

import time

import pytest

from app.llm.intent_rules import (
    PURPOSE_LABELS,
    clarification_question,
    extract_by_rules,
    normalize,
)
from app.schemas.enums import PurposeCode


def amount(text: str) -> int | None:
    match = extract_by_rules(text).requested_amount_rub
    return int(match.value) if match else None


def term(text: str) -> int | None:
    match = extract_by_rules(text).term_months
    return int(match.value) if match else None


def purpose(text: str) -> PurposeCode | None:
    match = extract_by_rules(text).purpose_code
    return PurposeCode(str(match.value)) if match else None


def test_normalization() -> None:
    assert normalize("  Ёлка  НА Склад \n") == "елка на склад"
    assert normalize("е́") == "е́"  # NFC не теряет комбинируемые знаки
    assert normalize("ＡＢ") == "ａｂ"  # casefold, без NFKC: полноширинные остаются


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3 000 000 ₽", 3_000_000),
        ("3 000 000 ₽", 3_000_000),
        ("3,5 млн", 3_500_000),
        ("1.2 млн", 1_200_000),
        ("500 тыс", 500_000),
        ("500к", 500_000),
        ("200k", 200_000),
        ("900 тыщ", 900_000),
        ("полтора миллиона", 1_500_000),
        ("полтора ляма", 1_500_000),
        ("3кк", 3_000_000),
        ("пол миллиона", 500_000),
        ("пару миллионов", 2_000_000),
        ("два миллиона", 2_000_000),
        ("пятьсот тысяч", 500_000),
        ("3 млн 500 тыс", 3_500_000),
        ("нужен миллион", 1_000_000),
        ("кредит 3000000 на оборудование", 3_000_000),
        ("600 тыс.", 600_000),
        ("800 000 руб", 800_000),
    ],
)
def test_amounts(text: str, expected: int) -> None:
    assert amount(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("на 2 года", 24),
        ("на полтора года", 18),
        ("18 мес", 18),
        ("на полгода", 6),
        ("на пол года", 6),
        ("на пару лет", 24),
        ("на год", 12),
        ("сроком на 36 месяцев", 36),
        ("на 3-х лет", 36),
        ("на 1,5 года", 18),
        ("на три года", 36),
        ("на квартал", 3),
        ("до 5 лет", 60),
    ],
)
def test_terms(text: str, expected: int) -> None:
    assert term(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("купить оборудование", PurposeCode.EQUIPMENT),
        ("новый станок", PurposeCode.EQUIPMENT),
        ("печь для пекарни", PurposeCode.EQUIPMENT),
        ("ремонт помещения", PurposeCode.RENOVATION),
        ("открыть филиал", PurposeCode.BUSINESS_EXPANSION),
        ("открыть вторую точку", PurposeCode.BUSINESS_EXPANSION),
        ("закуп к сезону", PurposeCode.INVENTORY),
        ("пополнить запас", PurposeCode.INVENTORY),
        ("оплатить поставщику", PurposeCode.SUPPLIERS),
        ("внести предоплату", PurposeCode.SUPPLIERS),
        ("на оборотные средства", PurposeCode.WORKING_CAPITAL),
        ("выплатить зарплаты", PurposeCode.WORKING_CAPITAL),
        ("закрыть кассовый разрыв", PurposeCode.WORKING_CAPITAL),
        ("закупить оборудование", PurposeCode.EQUIPMENT),  # «закуп» уступает конкретной цели
    ],
)
def test_purposes(text: str, expected: PurposeCode) -> None:
    assert purpose(text) == expected


def test_печенье_is_not_печь() -> None:
    assert purpose("продаём печенье") is None


def test_full_phrase_sources_and_fragments() -> None:
    draft = extract_by_rules("Купить печь за 3 млн на 3 года")
    assert draft.purpose_code is not None and draft.purpose_code.matched_text == "печь"
    assert draft.requested_amount_rub is not None
    assert draft.requested_amount_rub.matched_text == "3 млн"
    assert draft.term_months is not None and draft.term_months.matched_text == "на 3 года"
    assert draft.ambiguous == {}


@pytest.mark.parametrize(
    "text",
    [
        "оборот 5 млн",
        "выручка 12 млн в год",
        "платим 150 тыс в месяц",
        "у нас 15 сотрудников",
        "работаем 5 лет",
        "бизнесу 3 года",
        "на рынке уже 7 лет",
        "доход 300 тыс",
    ],
)
def test_noise_numbers_are_not_amount_or_term(text: str) -> None:
    draft = extract_by_rules(text)
    assert draft.requested_amount_rub is None and draft.term_months is None
    assert draft.ambiguous == {}


def test_marker_picks_requested_amount_among_noise() -> None:
    draft = extract_by_rules("Оборот 5 млн в месяц, нужно 2 млн на станок на 2 года")
    assert draft.requested_amount_rub is not None and draft.requested_amount_rub.value == 2_000_000
    assert draft.term_months is not None and draft.term_months.value == 24


def test_several_amounts_without_marker_are_ambiguous() -> None:
    draft = extract_by_rules("2 млн или 3 млн на ремонт")
    assert draft.requested_amount_rub is None
    assert draft.ambiguous == {"requested_amount_rub": [2_000_000, 3_000_000]}
    question = clarification_question(draft.ambiguous, ["requested_amount_rub"])
    assert question == "Какую сумму кредита вы хотите получить: 2 000 000 ₽ или 3 000 000 ₽?"


def test_several_purposes_give_question_with_options() -> None:
    draft = extract_by_rules("хочу открыть филиал и сделать ремонт")
    assert draft.purpose_code is None
    options = draft.ambiguous["purpose_code"]
    assert set(options) == {PurposeCode.RENOVATION, PurposeCode.BUSINESS_EXPANSION}
    question = clarification_question(draft.ambiguous, ["purpose_code"])
    assert question is not None
    assert all(PURPOSE_LABELS[PurposeCode(str(o))] in question for o in options)


def test_missing_fields_question() -> None:
    assert clarification_question({}, []) is None
    assert clarification_question({}, ["term_months"]) == "Уточните, пожалуйста, срок кредита."
    assert (
        clarification_question({}, ["purpose_code", "requested_amount_rub", "term_months"])
        == "Уточните, пожалуйста, цель, сумму и срок кредита."
    )


def test_out_of_range_term_is_dropped() -> None:
    assert term("ипотека на 20 лет") is None  # 240 мес. > 120


def test_digits_of_inn_and_account_are_not_amount() -> None:
    draft = extract_by_rules("ИНН 0099020010, счёт 40702810900000000010")
    assert draft.requested_amount_rub is None


@pytest.mark.parametrize(
    "text",
    [
        "1 " * 500,
        "9" * 1000,
        "на " * 333,
        "млн " * 250,
        "1 000 " * 166,
        "оборот " * 140,
        ("Купить печь за 3 млн на 3 года, оборот 5 млн в месяц. " * 20)[:1000],
        "1,1,1,1,1," * 100,
    ],
)
def test_rules_performance(text: str) -> None:
    """≤ 10 мс на 1000 символов, в том числе на патологических строках (backtracking)."""
    extract_by_rules(text)  # прогрев кеша регулярных выражений
    started = time.perf_counter()
    for _ in range(20):
        extract_by_rules(text[:1000])
    assert (time.perf_counter() - started) / 20 < 0.010
