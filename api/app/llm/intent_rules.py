"""Детерминированное распознавание потребности `extract_by_rules(text) -> IntentDraft` (#8).

Работает в любом режиме LLM, включая `disabled`. Регулярные выражения без вложенных
квантификаторов над пересекающимися классами, поэтому без катастрофического backtracking:
≤ 10 мс на 1000 символов (тест `test_rules_performance`).

Неоднозначности (issue #8):
- числа рядом с «оборот», «выручка», «в месяц», «сотрудник» — не сумма;
- несколько кандидатов без маркера («нужно», «кредит на») — `None` и уточняющий вопрос;
- несколько целей — `None` и вопрос с вариантами.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from app.schemas.enums import PurposeCode

Field = Literal["purpose_code", "requested_amount_rub", "term_months"]
FIELDS: tuple[Field, ...] = ("purpose_code", "requested_amount_rub", "term_months")

MIN_TERM, MAX_TERM = 1, 120
MIN_BARE_AMOUNT = 10_000  # число без единиц и валюты меньше этого — не сумма кредита
MAX_AMOUNT = 10**12

PURPOSE_LABELS: dict[PurposeCode, str] = {
    PurposeCode.EQUIPMENT: "покупка оборудования",
    PurposeCode.RENOVATION: "ремонт помещения",
    PurposeCode.BUSINESS_EXPANSION: "открытие новой точки или филиала",
    PurposeCode.INVENTORY: "закупка товара",
    PurposeCode.SUPPLIERS: "расчёты с поставщиками",
    PurposeCode.WORKING_CAPITAL: "пополнение оборотных средств",
}


@dataclass(frozen=True)
class FieldMatch:
    value: PurposeCode | int
    matched_text: str


@dataclass
class IntentDraft:
    """У каждого найденного поля — значение и фрагмент текста; источник — RULES."""

    purpose_code: FieldMatch | None = None
    requested_amount_rub: FieldMatch | None = None
    term_months: FieldMatch | None = None
    # поле → различные кандидаты, если выбрать один нельзя
    ambiguous: dict[Field, list[PurposeCode | int]] = field(default_factory=dict)

    def get(self, name: Field) -> FieldMatch | None:
        match: FieldMatch | None = getattr(self, name)
        return match

    @property
    def found(self) -> list[Field]:
        return [f for f in FIELDS if self.get(f) is not None]

    @property
    def single_purpose(self) -> bool:
        return self.purpose_code is not None

    def as_hint(self) -> dict[str, object]:
        """Подсказка для LLM: только значения и пометки неоднозначности, без фрагментов."""
        hint: dict[str, object] = {}
        for name in FIELDS:
            match = self.get(name)
            hint[name] = (
                (str(match.value) if isinstance(match.value, PurposeCode) else match.value)
                if match
                else None
            )
        hint["ambiguous"] = sorted(self.ambiguous)
        return hint


# --- Нормализация ----------------------------------------------------------------------

_SPACES = re.compile(r"[\s    ]+")


def normalize(text: str) -> str:
    """NFC → casefold → ё→е → неразрывные пробелы → схлопывание пробелов."""
    text = unicodedata.normalize("NFC", text).casefold().replace("ё", "е")
    return _SPACES.sub(" ", text).strip()


# --- Сумма -----------------------------------------------------------------------------

_NUM = r"(?<![\d.,])\d+(?: \d{3})*(?:[.,]\d+)?"
_BILLION = r"(?:млрд\w*|миллиард\w*)"
_MILLION = r"(?:кк|млн\.?|миллион\w*|мил\b|мулт\w*|лям\w*|лимон\w*)"
_THOUSAND = r"(?:тыс\w*\.?|тыщ\w*|т\.? ?р\.?(?!\w)|(?<=\d)[кk](?!\w))"
_CURRENCY = r"(?:₽|руб\w*\.?|р\.(?!\w)|р\b)"

_WORD_NUMBERS: dict[str, int] = {
    "один": 1, "одна": 1, "одного": 1, "два": 2, "две": 2, "двух": 2, "три": 3, "трех": 3,
    "четыре": 4, "четырех": 4, "пять": 5, "пяти": 5, "шесть": 6, "шести": 6, "семь": 7,
    "семи": 7, "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9, "десять": 10, "десяти": 10,
    "двенадцать": 12, "пятнадцать": 15, "восемнадцать": 18, "двадцать": 20, "тридцать": 30,
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}  # fmt: skip
_WORDS = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))

_AMOUNT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"\bполтор[аы] ?(?P<unit>{_MILLION}|{_THOUSAND})"), "half"),
    (re.compile(r"\bпол[- ]?(?P<unit>миллиона|млн|ляма|лимона)"), "semi"),
    (re.compile(rf"\bпар[уа] (?P<unit>{_MILLION})"), "pair"),
    (re.compile(rf"\b(?P<word>{_WORDS}) (?P<unit>{_BILLION}|{_MILLION}|{_THOUSAND})"), "word"),
    (
        re.compile(
            rf"(?P<num>{_NUM}) ?(?P<unit>{_BILLION}|{_MILLION}|{_THOUSAND})"
            rf"(?: ?(?P<rest>\d{{1,3}}) ?(?:тыс\w*\.?|тыщ\w*|(?<=\d)[кk](?!\w)))?"
            rf"(?: ?{_CURRENCY})?"
        ),
        "unit",
    ),
    (re.compile(rf"(?P<num>{_NUM}) ?{_CURRENCY}"), "currency"),
    (re.compile(r"\b(?P<unit>миллион|лям|лимон)\b"), "bare_word"),
    (re.compile(rf"(?P<num>{_NUM})(?![\d.,]|\s?%)"), "bare"),
)

# Маркер запрошенной суммы перед числом: «нужно 3 млн», «кредит на 500к».
_AMOUNT_MARKER = re.compile(
    r"(?:нуж\w*|кредит\w*|займ\w*|заем\w*|взять|получить|хоч\w*|хотим|хотел\w*|прош\w*|"
    r"просим|сумм\w*|требует\w*|необходим\w*|надо|лимит\w*|одолж\w*)[^.!?;]{0,12}$"
)
# «оборот», но не «оборотные средства» и не «пополнить оборот» (это цель)
_NOISE_BEFORE = re.compile(
    r"(?:(?<!пополнить )(?<!пополнение )(?<!пополнения )\bоборот(?!н)\w*|выручк\w*|"
    r"доход\w*|прибыл\w*|продаж\w*|плачу|платим|платеж\w*|зарплат\w* сотрудник\w*|"
    r"сотрудник\w*|оклад\w*)[^.!?;]{0,15}$"
)
_NOISE_AFTER = re.compile(
    r"^(?: ?(?:₽|руб\w*\.?))? ?(?:в |/ ?|за |ежемесячн\w*|каждый )(?:мес\w*|год\w*|день|недел\w*)|"
    r"^(?: ?(?:₽|руб\w*\.?))? ?(?:сотрудник\w*|человек\w*|работник\w*|клиент\w*|чел\b|"
    r"оборот(?!н)\w*|выручк\w*|%|процент\w*)"
)

_UNIT_FACTORS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(_BILLION), 1_000_000_000),
    (re.compile(_MILLION), 1_000_000),
    (re.compile(r"(?:тыс\w*\.?|тыщ\w*|т\.? ?р\.?|[кk])"), 1_000),  # без lookbehind
)


def _factor(unit: str) -> int:
    for pattern, factor in _UNIT_FACTORS:
        if pattern.fullmatch(unit):
            return factor
    return 1


def _to_decimal(raw: str) -> Decimal:
    return Decimal(raw.replace(" ", "").replace(",", "."))


@dataclass(frozen=True)
class _Candidate:
    value: int
    start: int
    end: int
    text: str
    marked: bool


def _overlaps(start: int, end: int, taken: list[tuple[int, int]]) -> bool:
    return any(start < e and s < end for s, e in taken)


def _amount_value(kind: str, m: re.Match[str]) -> int | None:
    groups = m.groupdict()
    unit = groups.get("unit") or ""
    if kind == "half":
        return int(Decimal("1.5") * _factor(unit))
    if kind == "semi":
        return 500_000
    if kind == "pair":
        return 2 * _factor(unit)
    if kind == "word":
        return _WORD_NUMBERS[groups["word"]] * _factor(unit)
    if kind == "bare_word":
        return 1_000_000
    number = _to_decimal(groups["num"])
    if kind == "unit":
        value = number * _factor(unit)
        if groups.get("rest"):
            value += int(groups["rest"]) * 1_000
        return int(value)
    if kind == "currency":
        return int(number) if number >= 1_000 else None
    return int(number) if number >= MIN_BARE_AMOUNT and number == int(number) else None


def _amount_candidates(text: str, taken: list[tuple[int, int]]) -> list[_Candidate]:
    found: list[_Candidate] = []
    for pattern, kind in _AMOUNT_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if _overlaps(start, end, taken):
                continue
            value = _amount_value(kind, m)
            if value is None or not 0 < value <= MAX_AMOUNT:
                continue
            before, after = text[max(0, start - 30) : start], text[end : end + 25]
            marked = bool(_AMOUNT_MARKER.search(before))
            if kind == "bare" and not marked:
                continue  # голое число без единиц — только после маркера суммы
            taken.append((start, end))
            if (_NOISE_BEFORE.search(before) and not marked) or _NOISE_AFTER.search(after):
                continue
            found.append(_Candidate(value, start, end, m.group().strip(), marked))
    return found


# --- Срок ------------------------------------------------------------------------------

_TERM_PREFIX = r"(?:(?:сроком |срок\w* )?(?:на |до )|срок\w* )?"
_TERM_NUM = r"(?<![\d.,])\d{1,3}(?:[.,]\d)?(?:-?х)?"
_YEARS = r"(?:год\w*|лет\b|г\.(?!\w))"
_MONTHS = r"(?:мес\w*\.?|мес\.)"
_TERM_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"{_TERM_PREFIX}пол[- ]?года\b"), "half_year"),
    (re.compile(rf"{_TERM_PREFIX}полтора (?:год\w*|лет)"), "one_and_half"),
    (re.compile(rf"{_TERM_PREFIX}пар[уа] лет"), "pair"),
    (re.compile(rf"{_TERM_PREFIX}квартал\b"), "quarter"),
    (re.compile(rf"{_TERM_PREFIX}(?P<word>{_WORDS}) (?P<unit>{_YEARS}|{_MONTHS})"), "word"),
    (re.compile(rf"{_TERM_PREFIX}(?P<num>{_TERM_NUM}) ?(?P<unit>{_YEARS}|{_MONTHS})"), "num"),
    (re.compile(r"(?:(?:сроком |срок\w* )?на |срок\w* )год\b"), "year"),
)
_TERM_NOISE_BEFORE = re.compile(
    r"(?:работа\w*|существ\w*|на рынке|бизнес\w*|компани\w*|опыт\w*|стаж\w*|уже|возраст\w*|"
    r"исполнилось|последн\w*|прошл\w*|назад|раз в)[^.!?;]{0,12}$"
)
_TERM_NOISE_AFTER = re.compile(
    r"^ ?(?:на рынке|работ\w*|назад|опыт\w*|подряд|существ\w*|бизнес\w*|компани\w*)"
)


def _term_value(kind: str, m: re.Match[str]) -> int | None:
    groups = m.groupdict()
    fixed = {"half_year": 6, "one_and_half": 18, "pair": 24, "quarter": 3, "year": 12}
    if kind in fixed:
        return fixed[kind]
    unit = groups["unit"]
    if kind == "word":
        count = Decimal(_WORD_NUMBERS[groups["word"]])
    else:
        count = _to_decimal(groups["num"].removesuffix("х").removesuffix("-"))
    months = count * 12 if re.fullmatch(_YEARS, unit) else count
    return int(months) if months == int(months) else None


def _term_candidates(text: str, taken: list[tuple[int, int]]) -> list[_Candidate]:
    found: list[_Candidate] = []
    for pattern, kind in _TERM_PATTERNS:
        for m in pattern.finditer(text):
            start, end = m.span()
            if _overlaps(start, end, taken):
                continue
            value = _term_value(kind, m)
            if value is None or not MIN_TERM <= value <= MAX_TERM:
                continue
            taken.append((start, end))
            matched = m.group().strip()
            before = text[max(0, start - 30) : start]
            marked = matched.startswith(("на ", "до ", "срок"))
            if not marked and (
                _TERM_NOISE_BEFORE.search(before) or _TERM_NOISE_AFTER.search(text[end:])
            ):
                continue
            found.append(_Candidate(value, start, end, matched, marked))
    return found


# --- Цель ------------------------------------------------------------------------------

_PURPOSES: tuple[tuple[PurposeCode, re.Pattern[str]], ...] = (
    (
        PurposeCode.EQUIPMENT,
        re.compile(
            r"оборудован\w*|станок|станк\w*|\bпеч(?:ь|и|ей|ам|ами)\b|\bпечк\w*|спецтехник\w*|"
            r"\bтехник[уиа]\b|автомобил\w*|грузовик\w*|\bмашин[уы]?\b|трактор\w*|экскаватор\w*|"
            r"холодильн\w*|кофемашин\w*|фургон\w*|погрузчик\w*|компьютер\w*|ноутбук\w*"
        ),
    ),
    (PurposeCode.RENOVATION, re.compile(r"ремонт\w*|отделк\w*|реконструкц\w*")),
    (
        PurposeCode.BUSINESS_EXPANSION,
        re.compile(
            r"филиал\w*|(?:втор\w*|трет\w*|нов\w*|еще одн\w*|дополнительн\w*) "
            r"(?:точк\w*|магазин\w*|кофейн\w*|салон\w*|офис\w*|пекарн\w*|цех\w*|ресторан\w*|кафе|отделени\w*|пункт\w*)|"
            r"расширени\w*|расширить|масштабир\w*|открыт\w* (?:точк|магазин|филиал|кофейн)\w*"
        ),
    ),
    (PurposeCode.INVENTORY, re.compile(r"закуп\w*|запас\w*|сезон\w*|товар\w*|\bпарти[юи]\b")),
    (PurposeCode.SUPPLIERS, re.compile(r"поставщик\w*|предоплат\w*|сырь\w*")),
    (
        PurposeCode.WORKING_CAPITAL,
        re.compile(
            r"оборотн\w*|пополн\w* оборот\w*|на оборот\b|зарплат\w*|заработн\w* плат\w*|"
            r"кассов\w* разрыв\w*|\bразрыв\w*|налог\w*|аренд\w*|текущ\w* расход\w*"
        ),
    ),
)
# «Закупить оборудование» — покупка оборудования, а не закупка товара.
_WEAK_INVENTORY = re.compile(r"закуп\w*")


def _purposes(text: str) -> dict[PurposeCode, str]:
    found: dict[PurposeCode, str] = {}
    for code, pattern in _PURPOSES:
        matches = [m.group() for m in pattern.finditer(text)]
        if matches:
            found[code] = matches[0]
    inventory = found.get(PurposeCode.INVENTORY)
    if inventory and len(found) > 1 and _WEAK_INVENTORY.fullmatch(inventory):
        # все совпадения INVENTORY — только «закуп…»: уступает конкретной цели
        others = [m.group() for m in _PURPOSES[3][1].finditer(text)]
        if all(_WEAK_INVENTORY.fullmatch(o) for o in others):
            del found[PurposeCode.INVENTORY]
    return found


# --- Выбор -----------------------------------------------------------------------------


def _choose(candidates: list[_Candidate]) -> tuple[_Candidate | None, list[int]]:
    values = sorted({c.value for c in candidates})
    if len(values) == 1:
        return next(c for c in candidates if c.value == values[0]), []
    if not values:
        return None, []
    marked = sorted({c.value for c in candidates if c.marked})
    if len(marked) == 1:
        return next(c for c in candidates if c.marked), []
    return None, values


def extract_by_rules(text: str) -> IntentDraft:
    norm = normalize(text)
    draft = IntentDraft()
    taken: list[tuple[int, int]] = []
    # Сумма раньше срока: «500 тыс» не станет сроком, «на 2 года» не станет суммой.
    amount, amount_options = _choose(_amount_candidates(norm, taken))
    term, term_options = _choose(_term_candidates(norm, taken))
    if amount:
        draft.requested_amount_rub = FieldMatch(amount.value, amount.text)
    elif amount_options:
        draft.ambiguous["requested_amount_rub"] = list(amount_options)
    if term:
        draft.term_months = FieldMatch(term.value, term.text)
    elif term_options:
        draft.ambiguous["term_months"] = list(term_options)
    purposes = _purposes(norm)
    if len(purposes) == 1:
        [(code, matched)] = purposes.items()
        draft.purpose_code = FieldMatch(code, matched)
    elif purposes:
        draft.ambiguous["purpose_code"] = [c for c, _ in _PURPOSES if c in purposes]
    return draft


# --- Уточняющие вопросы (шаблоны: LLM для клиентских текстов не используется) --------


def _rub(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " ₽"


def _months(value: int) -> str:
    return f"{value} мес."


def clarification_question(
    ambiguous: dict[Field, list[PurposeCode | int]], missing: list[Field]
) -> str | None:
    if "purpose_code" in ambiguous:
        options = [PURPOSE_LABELS[PurposeCode(str(c))] for c in ambiguous["purpose_code"]]
        return f"Уточните цель кредита: {', '.join(options[:-1])} или {options[-1]}?"
    if "requested_amount_rub" in ambiguous:
        options = [_rub(int(v)) for v in ambiguous["requested_amount_rub"]]
        return (
            f"Какую сумму кредита вы хотите получить: {', '.join(options[:-1])} или {options[-1]}?"
        )
    if "term_months" in ambiguous:
        options = [_months(int(v)) for v in ambiguous["term_months"]]
        return f"На какой срок нужен кредит: {', '.join(options[:-1])} или {options[-1]}?"
    if not missing:
        return None
    names = {"purpose_code": "цель", "requested_amount_rub": "сумму", "term_months": "срок"}
    parts = [names[f] for f in FIELDS if f in missing]
    joined = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} и {parts[-1]}"
    return f"Уточните, пожалуйста, {joined} кредита."
