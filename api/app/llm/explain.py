"""Заключение для менеджера `explain_risk` (design.md §3.6, issue #8).

Модель пишет числа только плейсхолдерами (`{dscr}`, `{payment}`, `{limit}`, `{cfads}`,
`{revenue_change}`, `{debt}`, `{amount}`, `{term}`); значения подставляет backend из
расчёта (`app.llm.display`). Валидаторы по порядку: схема → коды ⊆ кодов расчёта и каждый
риск-код покрыт → нет цифр и незнакомых плейсхолдеров → нет стоп-фраз и разметки → длины.
Нарушение → один повтор с описанием ошибки → шаблон. Шаблон проходит те же валидаторы.

Контекст модели — коды, уровень риска, цель и продукт, имена плейсхолдеров и
маскированный текст клиента. Значений метрик, ИНН, ФИО, названий и счетов в нём нет.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic import Field as PydanticField

from app.core.logs import get_logger
from app.llm.base import LLMClient, LlmError, LlmInvalidOutput, LlmTask, context_hash
from app.llm.display import format_money, format_months, format_percent
from app.llm.parsing import parse_json_object
from app.llm.pii import minimize_client_text
from app.llm.prompts import REPAIR_KEY
from app.schemas.enums import FallbackReason, ReasonCode, RiskLevel
from app.schemas.manager import AiFactor, AiReportBody, Scoring

PROMPT_VERSION = "v1"
PROMPT_LABEL = f"{LlmTask.EXPLAIN_RISK.value}/{PROMPT_VERSION}"  # ai_reports.prompt_version
MAX_SUMMARY, MAX_FACTOR, MAX_QUESTION, MAX_QUESTIONS = 600, 300, 200, 3
logger = get_logger("app.llm.explain")


class _LlmFactor(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str
    text: str


class RiskReportLlm(BaseModel):
    """Ответ модели до подстановки значений. Коды — строки: проверяет валидатор кодов."""

    model_config = ConfigDict(extra="forbid", strict=True)

    summary: str
    risk_factors: list[_LlmFactor]
    positive_factors: list[_LlmFactor]
    manager_questions: list[str] = PydanticField(max_length=MAX_QUESTIONS)

    _FACTOR: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["code", "text"],
        "properties": {"code": {"type": "string"}, "text": {"type": "string"}},
    }
    LLM_JSON_SCHEMA: ClassVar[dict[str, Any]] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "risk_factors", "positive_factors", "manager_questions"],
        "properties": {
            "summary": {"type": "string"},
            "risk_factors": {"type": "array", "items": _FACTOR},
            "positive_factors": {"type": "array", "items": _FACTOR},
            "manager_questions": {"type": "array", "items": {"type": "string"}},
        },
    }


# --- Плейсхолдеры ----------------------------------------------------------------------

PLACEHOLDER_MEANINGS: dict[str, str] = {
    "dscr": "DSCR — коэффициент покрытия платежей денежным потоком",
    "payment": "ежемесячный платёж по запрошенному кредиту",
    "limit": "расчётный лимит кредита",
    "cfads": "денежный поток для обслуживания долга в месяц",
    "revenue_change": "изменение выручки за последние полгода",
    "debt": "текущие платежи по другим кредитам в месяц",
    "amount": "запрошенная сумма кредита",
    "term": "запрошенный срок кредита",
}
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class ReportInputs:
    """Всё, что нужно заключению, из БД: расчёт карточки и условия заявки."""

    scoring: Scoring
    purpose_code: str | None
    product_id: str | None
    amount_rub: int | None
    term_months: int | None
    client_text: str | None = None
    person_names: tuple[str, ...] = ()
    company_names: tuple[str, ...] = ()

    @property
    def risk_codes(self) -> list[str]:
        return [c.value for c in self.scoring.reason_codes]

    @property
    def positive_codes(self) -> list[str]:
        return [c.value for c in self.scoring.positive_codes]


def placeholder_values(inputs: ReportInputs) -> dict[str, str]:
    """Значения в формате показа; плейсхолдер без значения (расчёт SKIPPED) недоступен."""
    s = inputs.scoring
    values = {
        "dscr": s.dscr,
        "payment": format_money(s.monthly_payment_rub) if s.monthly_payment_rub else None,
        "limit": format_money(s.limit_rub) if s.limit_rub else None,
        "cfads": format_money(s.cfads_monthly_rub) if s.cfads_monthly_rub else None,
        "revenue_change": format_percent(s.revenue_change_pct) if s.revenue_change_pct else None,
        "debt": format_money(s.existing_debt_payments_rub),
        "amount": format_money(str(inputs.amount_rub), kopecks=False)
        if inputs.amount_rub
        else None,
        "term": format_months(inputs.term_months) if inputs.term_months else None,
    }
    return {k: v for k, v in values.items() if v is not None}


# --- Тексты по кодам (без цифр: проходят те же валидаторы, что и ответ модели) ----------


@dataclass(frozen=True)
class CodePhrase:
    with_values: str  # с плейсхолдерами
    plain: str  # если нужного плейсхолдера нет
    question: str | None = None


CODE_PHRASES: dict[ReasonCode, CodePhrase] = {
    ReasonCode.DSCR_BELOW_ONE: CodePhrase(
        "DSCR {dscr} ниже единицы: денежного потока {cfads} не хватает на платежи по кредитам.",
        "DSCR ниже единицы: денежного потока не хватает на платежи по кредитам.",
        "Есть ли у компании дополнительные источники погашения кредита?",
    ),
    ReasonCode.DSCR_BELOW_TARGET: CodePhrase(
        "DSCR {dscr} ниже целевого уровня банка: запас по платежу {payment} невелик.",
        "DSCR ниже целевого уровня банка: запас по платежу невелик.",
        "Есть ли у компании дополнительные источники погашения кредита?",
    ),
    ReasonCode.CREDIT_HISTORY_SERIOUS: CodePhrase(
        "В кредитной истории есть серьёзные нарушения.",
        "В кредитной истории есть серьёзные нарушения.",
        "Чем вызваны нарушения в кредитной истории и урегулированы ли они?",
    ),
    ReasonCode.CREDIT_HISTORY_MINOR: CodePhrase(
        "В кредитной истории есть незначительные нарушения.",
        "В кредитной истории есть незначительные нарушения.",
        "Чем вызваны нарушения в кредитной истории и урегулированы ли они?",
    ),
    ReasonCode.CREDIT_HISTORY_UNKNOWN: CodePhrase(
        "Кредитная история отсутствует.",
        "Кредитная история отсутствует.",
        "Были ли у компании кредиты или займы в других банках?",
    ),
    ReasonCode.REVENUE_DECLINE: CodePhrase(
        "Выручка снизилась: изменение {revenue_change}.",
        "Выручка снизилась.",
        "С чем связано снижение выручки и ожидается ли восстановление?",
    ),
    ReasonCode.REVENUE_SHARP_DECLINE: CodePhrase(
        "Выручка резко снизилась: изменение {revenue_change}.",
        "Выручка резко снизилась.",
        "С чем связано снижение выручки и ожидается ли восстановление?",
    ),
    ReasonCode.YOUNG_BUSINESS: CodePhrase(
        "Бизнес работает меньше двух лет.",
        "Бизнес работает меньше двух лет.",
        "Есть ли у владельца опыт работы в этой отрасли?",
    ),
    ReasonCode.DSCR_MEETS_TARGET: CodePhrase(
        "DSCR {dscr} не ниже целевого уровня банка.",
        "DSCR не ниже целевого уровня банка.",
    ),
    ReasonCode.CLEAN_CREDIT_HISTORY: CodePhrase(
        "Кредитная история без нарушений.", "Кредитная история без нарушений."
    ),
    ReasonCode.REVENUE_STABLE_OR_GROWING: CodePhrase(
        "Выручка стабильна или растёт: изменение {revenue_change}.",
        "Выручка стабильна или растёт.",
    ),
    ReasonCode.ESTABLISHED_BUSINESS: CodePhrase(
        "Бизнес работает два года и больше.", "Бизнес работает два года и больше."
    ),
}

SUMMARIES: dict[RiskLevel | None, CodePhrase] = {
    RiskLevel.LOW: CodePhrase(
        "Расчёт показывает низкий уровень риска: DSCR {dscr}, ежемесячный платёж {payment}, "
        "расчётный лимит {limit}. Решение принимает менеджер.",
        "Расчёт показывает низкий уровень риска. Решение принимает менеджер.",
    ),
    RiskLevel.MODERATE: CodePhrase(
        "Расчёт показывает умеренный уровень риска: DSCR {dscr} при платеже {payment}, "
        "расчётный лимит {limit}. Решение принимает менеджер.",
        "Расчёт показывает умеренный уровень риска. Решение принимает менеджер.",
    ),
    RiskLevel.HIGH: CodePhrase(
        "Расчёт показывает высокий уровень риска: DSCR {dscr} при платеже {payment}, "
        "расчётный лимит {limit}. Решение принимает менеджер.",
        "Расчёт показывает высокий уровень риска. Решение принимает менеджер.",
    ),
    None: CodePhrase(
        "Расчёт не выполнен: данных выписки недостаточно для оценки. Решение принимает менеджер.",
        "Расчёт не выполнен: данных выписки недостаточно для оценки. Решение принимает менеджер.",
    ),
}


def _phrase(phrase: CodePhrase, available: Mapping[str, str]) -> str:
    used = set(_PLACEHOLDER.findall(phrase.with_values))
    return phrase.with_values if used <= set(available) else phrase.plain


def template_report(inputs: ReportInputs) -> RiskReportLlm:
    """Шаблон по кодам и уровню риска — до подстановки, как ответ модели."""
    available = placeholder_values(inputs)
    questions: list[str] = []
    for code in inputs.scoring.reason_codes:
        question = CODE_PHRASES[code].question
        if question and question not in questions:
            questions.append(question)
    return RiskReportLlm(
        summary=_phrase(SUMMARIES[inputs.scoring.risk_level], available),
        risk_factors=[
            _LlmFactor(code=c.value, text=_phrase(CODE_PHRASES[c], available))
            for c in inputs.scoring.reason_codes
        ],
        positive_factors=[
            _LlmFactor(code=c.value, text=_phrase(CODE_PHRASES[c], available))
            for c in inputs.scoring.positive_codes
        ],
        manager_questions=questions[:MAX_QUESTIONS],
    )


# --- Контекст --------------------------------------------------------------------------


def explain_context(inputs: ReportInputs) -> dict[str, Any]:
    available = placeholder_values(inputs)
    s = inputs.scoring
    return {
        "calculation": {
            "calculation_status": s.calculation_status.value,
            "risk_level": s.risk_level.value if s.risk_level else None,
            "purpose_code": inputs.purpose_code,
            "product_id": inputs.product_id,
            "risk_codes": [
                {"code": c.value, "meaning": CODE_PHRASES[c].plain} for c in s.reason_codes
            ],
            "positive_codes": [
                {"code": c.value, "meaning": CODE_PHRASES[c].plain} for c in s.positive_codes
            ],
            "placeholders": [
                {"name": f"{{{name}}}", "meaning": meaning}
                for name, meaning in PLACEHOLDER_MEANINGS.items()
                if name in available
            ],
        },
        "client_text": minimize_client_text(
            inputs.client_text,
            person_names=inputs.person_names,
            company_names=inputs.company_names,
        ),
    }


# --- Валидаторы ------------------------------------------------------------------------


class ReportViolation(Exception):
    """Нарушение правил ответа. Сообщение — наше описание без текста модели и клиента:
    оно уходит модели в повторе и в лог."""

    def __init__(self, check: str, message: str) -> None:
        super().__init__(message)
        self.check, self.message = check, message


_STOP = re.compile(
    r"одобр|гарантир|рекоменду\w* (?:выдать|выдачу|отказать|отказ)|"
    r"кредит (?:будет )?(?:выдан|предоставлен)|решение (?:принято|положительное)",
    re.IGNORECASE,
)
_MARKUP = re.compile(r"<[^>]*>|[<>]|```|\]\(|https?://|www\.|[*#_`|]{2,}|^\s*[-*#>]\s", re.M)
_LEAK = re.compile(r"плейсхолдер|placeholder|инструкци|system|промпт|prompt", re.IGNORECASE)
_ALLOWED_LATIN = re.compile(r"\b(?:DSCR|CFADS)\b")


def _texts(report: RiskReportLlm) -> Iterable[tuple[str, str]]:
    yield "summary", report.summary
    for i, f in enumerate(report.risk_factors):
        yield f"risk_factors[{i}].text", f.text
    for i, f in enumerate(report.positive_factors):
        yield f"positive_factors[{i}].text", f.text
    for i, q in enumerate(report.manager_questions):
        yield f"manager_questions[{i}]", q


def _check_codes(report: RiskReportLlm, inputs: ReportInputs) -> None:
    risk = [f.code for f in report.risk_factors]
    positive = [f.code for f in report.positive_factors]
    if len(set(risk)) != len(risk) or len(set(positive)) != len(positive):
        raise ReportViolation("codes", "каждый код допускается в списке только один раз.")
    unknown = set(risk) - set(inputs.risk_codes)
    if unknown:
        raise ReportViolation(
            "codes",
            f"в risk_factors недопустимые коды; разрешены только {inputs.risk_codes}.",
        )
    unknown = set(positive) - set(inputs.positive_codes)
    if unknown:
        raise ReportViolation(
            "codes",
            f"в positive_factors недопустимые коды; разрешены только {inputs.positive_codes}.",
        )
    missing = [c for c in inputs.risk_codes if c not in risk]
    if missing:
        raise ReportViolation("codes", f"в risk_factors не описаны коды {missing}.")


def _check_numbers(report: RiskReportLlm, available: Mapping[str, str]) -> None:
    for where, text in _texts(report):
        unknown = sorted(set(_PLACEHOLDER.findall(text)) - set(available))
        if unknown:
            raise ReportViolation(
                "placeholders",
                f"{where}: незнакомые плейсхолдеры; доступны только {sorted(available)}.",
            )
        rest = _PLACEHOLDER.sub("", text)
        if any(ch.isnumeric() for ch in rest) or re.search(r"[{}%₽]", rest):
            raise ReportViolation(
                "digits", f"{where}: цифры, проценты и суммы допустимы только плейсхолдерами."
            )


def _check_wording(report: RiskReportLlm) -> None:
    for where, text in _texts(report):
        # Не позволяем скрыть стоп-фразу zero-width/bidi-символами или смешением
        # латинских и кириллических букв. Отображаем только исходный проверенный текст.
        if any(unicodedata.category(ch).startswith("C") and ch not in "\n\t\r" for ch in text):
            raise ReportViolation("wording", f"{where}: недопустимые управляющие символы.")
        normalized = unicodedata.normalize("NFKC", text).casefold()
        normalized = normalized.translate(str.maketrans("aceopxy", "асеорху"))
        if _STOP.search(" ".join(normalized.split())):
            raise ReportViolation(
                "stop_phrase", f"{where}: нельзя обещать или принимать решение по кредиту."
            )
        prose = _PLACEHOLDER.sub("", text)
        if _MARKUP.search(prose) or re.search(r"[*_`#|]", prose):
            raise ReportViolation("markup", f"{where}: только обычный текст без разметки.")
        if _LEAK.search(text):
            raise ReportViolation("leak", f"{where}: не упоминай инструкции и служебные поля.")
        letters = [ch for ch in _ALLOWED_LATIN.sub("", prose) if ch.isalpha()]
        foreign = sum(not ("а" <= ch.casefold() <= "я" or ch.casefold() == "ё") for ch in letters)
        if letters and foreign > len(letters) * 0.2:
            raise ReportViolation("language", f"{where}: текст должен быть на русском языке.")


def _render(text: str, available: Mapping[str, str]) -> str:
    return _PLACEHOLDER.sub(lambda m: available[m.group(1)], " ".join(text.split()))


def _check_lengths(body: AiReportBody) -> None:
    if not body.summary or len(body.summary) > MAX_SUMMARY:
        raise ReportViolation("length", f"summary: от 1 до {MAX_SUMMARY} символов.")
    for f in (*body.risk_factors, *body.positive_factors):
        if not f.text or len(f.text) > MAX_FACTOR:
            raise ReportViolation("length", f"текст фактора: от 1 до {MAX_FACTOR} символов.")
    for q in body.manager_questions:
        if not q or len(q) > MAX_QUESTION:
            raise ReportViolation("length", f"вопрос менеджеру: от 1 до {MAX_QUESTION} символов.")


def validate_report(data: Any, inputs: ReportInputs) -> AiReportBody:
    """Все проверки по порядку; результат — тело с подставленными значениями."""
    try:
        report = data if isinstance(data, RiskReportLlm) else RiskReportLlm.model_validate(data)
    except ValidationError:
        raise ReportViolation(
            "schema", "ответ не соответствует схеме: проверь типы и набор полей."
        ) from None
    available = placeholder_values(inputs)
    _check_codes(report, inputs)
    _check_numbers(report, available)
    _check_wording(report)
    summary = _render(report.summary, available)
    if not summary or len(summary) > MAX_SUMMARY:  # AiReportBody ограничивает summary тем же
        raise ReportViolation("length", f"summary: от 1 до {MAX_SUMMARY} символов.")
    body = AiReportBody(
        summary=summary,
        risk_factors=[
            AiFactor(code=ReasonCode(f.code), text=_render(f.text, available))
            for f in report.risk_factors
        ],
        positive_factors=[
            AiFactor(code=ReasonCode(f.code), text=_render(f.text, available))
            for f in report.positive_factors
        ],
        manager_questions=[_render(q, available) for q in report.manager_questions],
    )
    _check_lengths(body)
    return body


def render_template(inputs: ReportInputs) -> AiReportBody:
    return validate_report(template_report(inputs), inputs)


# --- Генерация -------------------------------------------------------------------------


@dataclass
class ExplainOutcome:
    body: AiReportBody
    context_hash: str
    model_id: str | None = None
    fallback_reason: FallbackReason | None = None
    violations: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.fallback_reason is None


async def explain(llm: LLMClient, inputs: ReportInputs) -> ExplainOutcome:
    """Вызов модели с одним повтором после нарушения; дальше — шаблон.

    Таймаут бюджета (`asyncio.timeout` у вызывающего) прерывает эту корутину целиком;
    вызывающий сам ставит шаблон с `TIMEOUT`.
    """
    context = explain_context(inputs)
    digest = context_hash(LlmTask.EXPLAIN_RISK, PROMPT_VERSION, context)
    outcome = ExplainOutcome(body=render_template(inputs), context_hash=digest)
    attempt_context: dict[str, Any] = context
    for attempt in (1, 2):
        try:
            result = await llm.complete(
                LlmTask.EXPLAIN_RISK, PROMPT_VERSION, attempt_context, RiskReportLlm
            )
            body = validate_report(parse_json_object(result.content), inputs)
        except LlmInvalidOutput as exc:
            violation = ReportViolation("json", f"{exc}: нужен один JSON-объект.")
        except ReportViolation as exc:
            violation = exc
        except LlmError as exc:
            outcome.fallback_reason = exc.reason
            return outcome
        else:
            outcome.body, outcome.model_id = body, result.model_id
            return outcome
        outcome.violations.append(violation.check)
        logger.info(
            "ai_report.invalid_output", check=violation.check, attempt=attempt, context_hash=digest
        )
        attempt_context = {**context, REPAIR_KEY: violation.message}
    outcome.fallback_reason = FallbackReason.INVALID_OUTPUT
    return outcome
