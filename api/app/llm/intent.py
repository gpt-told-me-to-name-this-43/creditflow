"""Распознавание потребности: правила → LLM (`extract_intent`) → слияние (design.md §3.6).

| Поле | Правила | LLM | Итог |
| Сумма, срок | есть | любое | правила |
| Сумма, срок | нет | есть | LLM |
| Цель | один кандидат | другое | правила |
| Цель | несколько | есть | LLM |
| Любое | нет | нет | `null` |

При неоднозначности правил LLM может выбрать только один из найденных правилами вариантов.
Статусы: `OK` — найдены все три поля; `NEEDS_CLARIFICATION` — есть вопрос; `UNAVAILABLE` —
провайдер недоступен и правила ничего не нашли. Заявку модуль не читает и не меняет.
"""

import asyncio
import re
import unicodedata
from collections.abc import Iterable
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from app.core.logs import get_logger
from app.llm.base import LLMClient, LlmError, LlmInvalidOutput, LlmTask
from app.llm.intent_rules import (
    FIELDS,
    MAX_AMOUNT,
    MAX_TERM,
    MIN_TERM,
    Field,
    IntentDraft,
    clarification_question,
    extract_by_rules,
    normalize,
)
from app.llm.parsing import parse_json_object
from app.llm.pii import mask_digit_runs, minimize_client_text
from app.schemas.client import (
    AmountSuggestion,
    FieldSource,
    InterpretResponse,
    InterpretStatus,
    InterpretSuggestions,
    PurposeSuggestion,
    TermSuggestion,
)
from app.schemas.enums import PurposeCode

PROMPT_VERSION = "v1"
MAX_QUESTION_LENGTH = 200
logger = get_logger("app.llm.intent")


class IntentLlmOutput(BaseModel):
    """Ответ `extract_intent`; невалидное поле → `null` (`parse_intent`)."""

    model_config = ConfigDict(extra="ignore")

    purpose_code: PurposeCode | None = None
    requested_amount_rub: int | None = None
    term_months: int | None = None
    clarification_question: str | None = None

    LLM_JSON_SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "purpose_code",
            "requested_amount_rub",
            "term_months",
            "clarification_question",
        ],
        "properties": {
            "purpose_code": {"type": ["string", "null"], "enum": [*PurposeCode, None]},
            "requested_amount_rub": {"type": ["integer", "null"]},
            "term_months": {"type": ["integer", "null"]},
            "clarification_question": {"type": ["string", "null"]},
        },
    }


# Вопрос модели показывается клиенту, поэтому проходит те же запреты, что и заключение.
_QUESTION_FORBIDDEN = re.compile(
    r"одобр|гарантир|рекоменду|отказ|выдан|<|>|```|\]\(|https?:|www\.|\{|\}|промпт|prompt|"
    r"инструкц|system",
    re.IGNORECASE,
)
# Число в тексте клиента: иначе предложение модели о сумме или сроке — догадка.
_HAS_QUANTITY = re.compile(
    r"\d|полтор|\bпол|пар[уа]\b|миллион|млн|лям|лимон|тыс|тыщ|\bкк\b|"
    r"\b(?:один|одна|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять|сто|двести|"
    r"триста|пятьсот)\b|\bгод\b|квартал"
)


def _int_field(value: object, low: int, high: int) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and low <= value <= high else None


def _question(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    letters = [ch for ch in text if ch.isalpha()]
    foreign = sum(not ("а" <= ch.casefold() <= "я" or ch.casefold() == "ё") for ch in letters)
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = normalized.translate(str.maketrans("aceopxy", "асеорху"))
    if (
        not text
        or len(text) > MAX_QUESTION_LENGTH
        or not text.endswith("?")
        or _QUESTION_FORBIDDEN.search(text)
        or _QUESTION_FORBIDDEN.search(normalized)
        or any(unicodedata.category(ch).startswith("C") for ch in text)
        or re.search(r"[*_`#|]", text)
        or (letters and foreign > len(letters) * 0.2)
    ):
        return None
    return text


def parse_intent(content: str) -> IntentLlmOutput:
    """Каждое поле проверяется отдельно: невалидное становится `null`, остальные остаются."""
    data = parse_json_object(content)
    purpose = data.get("purpose_code")
    return IntentLlmOutput(
        purpose_code=PurposeCode(purpose)
        if isinstance(purpose, str) and purpose in set(PurposeCode)
        else None,
        requested_amount_rub=_int_field(data.get("requested_amount_rub"), 1, MAX_AMOUNT),
        term_months=_int_field(data.get("term_months"), MIN_TERM, MAX_TERM),
        clarification_question=_question(data.get("clarification_question")),
    )


def intent_context(draft: IntentDraft, masked_text: str) -> dict[str, Any]:
    """Контекст `extract_intent`: только маскированный текст и подсказка правил."""
    hint = draft.as_hint()
    for name in FIELDS:
        match = draft.get(name)
        if match is not None and mask_digit_runs(match.matched_text) != match.matched_text:
            # Длинный идентификатор иногда похож на сумму. Не возвращаем его
            # числовое значение в запрос через подсказку правил после маскирования текста.
            hint[name] = None
    return {"client_text": masked_text, "rules": hint}


def merge(
    draft: IntentDraft, llm: IntentLlmOutput | None, *, llm_unavailable: bool, text: str
) -> InterpretResponse:
    has_quantity = bool(_HAS_QUANTITY.search(normalize(text)))
    values: dict[Field, tuple[Any, FieldSource, str | None]] = {}
    ambiguous = dict(draft.ambiguous)
    for name in FIELDS:
        rule = draft.get(name)
        if rule is not None:
            values[name] = (rule.value, FieldSource.RULES, rule.matched_text)
            continue
        candidate = getattr(llm, name) if llm else None
        if candidate is None or (name != "purpose_code" and not has_quantity):
            continue
        options = ambiguous.get(name)
        if options is not None and candidate not in options:
            continue  # модель выбирает только из вариантов, найденных в тексте
        values[name] = (candidate, FieldSource.LLM, None)
        ambiguous.pop(name, None)

    suggestion = InterpretSuggestions(
        purpose_code=PurposeSuggestion(
            value=values["purpose_code"][0],
            source=values["purpose_code"][1],
            matched_text=values["purpose_code"][2],
        )
        if "purpose_code" in values
        else None,
        requested_amount_rub=AmountSuggestion(
            value=values["requested_amount_rub"][0],
            source=values["requested_amount_rub"][1],
            matched_text=values["requested_amount_rub"][2],
        )
        if "requested_amount_rub" in values
        else None,
        term_months=TermSuggestion(
            value=values["term_months"][0],
            source=values["term_months"][1],
            matched_text=values["term_months"][2],
        )
        if "term_months" in values
        else None,
    )
    if len(values) == len(FIELDS):
        return InterpretResponse(
            status=InterpretStatus.OK, suggestion=suggestion, clarification_question=None
        )
    if llm_unavailable and not values and not ambiguous:
        return InterpretResponse(
            status=InterpretStatus.UNAVAILABLE, suggestion=suggestion, clarification_question=None
        )
    missing = [f for f in FIELDS if f not in values]
    question = clarification_question(ambiguous, missing) if ambiguous else None
    if question is None and llm is not None and llm.clarification_question:
        question = llm.clarification_question
    question = question or clarification_question({}, missing)
    return InterpretResponse(
        status=InterpretStatus.NEEDS_CLARIFICATION,
        suggestion=suggestion,
        clarification_question=question,
    )


async def interpret_text(
    text: str,
    llm: LLMClient,
    timeout_seconds: float,
    *,
    person_names: Iterable[str] = (),
    company_names: Iterable[str] = (),
) -> InterpretResponse:
    """Правила всегда; LLM — только если правила не дали все три поля однозначно.
    Сбой, таймаут или промах replay — результат правил (HTTP-ошибок нет)."""
    draft = extract_by_rules(text)
    if len(draft.found) == len(FIELDS):
        return merge(draft, None, llm_unavailable=False, text=text)
    masked = minimize_client_text(text, person_names=person_names, company_names=company_names)
    context = intent_context(draft, masked)
    parsed: IntentLlmOutput | None = None
    unavailable = False
    try:
        async with asyncio.timeout(timeout_seconds):
            result = await llm.complete(
                LlmTask.EXTRACT_INTENT, PROMPT_VERSION, context, IntentLlmOutput
            )
        parsed = parse_intent(result.content)
    except LlmInvalidOutput:
        logger.info("interpret.llm_result", outcome="invalid_output")
    except LlmError as exc:
        unavailable = True
        logger.info("interpret.llm_result", outcome=exc.reason.value.lower())
    except TimeoutError:
        unavailable = True
        logger.info("interpret.llm_result", outcome="timeout")
    except Exception as exc:  # исключения стороннего SDK могут содержать ответ или ключ
        unavailable = True
        logger.error("interpret.llm_result", outcome="error", error_type=type(exc).__name__)
    return merge(draft, parsed, llm_unavailable=unavailable, text=text)
