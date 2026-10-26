"""Минимизация данных перед вызовом провайдера (design.md §3.6, §4).

В провайдер не уходят ИНН, ФИО, названия компаний и номера счетов: контексты задач их не
содержат вовсе, а в тексте клиента маскируются последовательности из 10 и более цифр
(ИНН, счёт, телефон — в том числе с пробелами, дефисами и скобками между цифрами) и
известные backend-у название компании и ФИО заявителя.
"""

import re
import unicodedata
from collections.abc import Iterable

DIGITS_MASK = "[скрыто]"
NAME_MASK = "[имя скрыто]"
COMPANY_MASK = "[компания скрыта]"
MIN_MASKED_DIGITS = 10

# Цифры с разделителями (до двух подряд) между ними: «0099 0200 10», «+7 (999) 123-45-67».
_DIGIT_RUN = re.compile(r"\d(?:[\s\-().]*\d)+")
_QUOTES = "«»\"'„“”"
_LEGAL_FORMS = re.compile(r"^(ооо|ао|пао|зао|оао|ип)\s+", re.IGNORECASE)


def mask_digit_runs(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        digits = sum(ch.isdigit() for ch in match.group())
        return DIGITS_MASK if digits >= MIN_MASKED_DIGITS else match.group()

    return _DIGIT_RUN.sub(replace, text)


def _name_variants(full_name: str) -> list[str]:
    # Фамилия отдельно тоже узнаёт человека; имя и отчество по отдельности — нет.
    parts = [p for p in re.split(r"\s+", full_name.strip()) if p]
    variants = [full_name.strip()] if parts else []
    if parts and len(parts[0]) >= 3:
        variants.append(parts[0])
        if parts[0].endswith(("а", "я")) and len(parts[0]) >= 5:
            variants.append(parts[0][:-1])  # Кузнецовой/Кузнецову и другие падежи фамилии
    if len(parts) > 1:
        variants.extend(" ".join(pair) for pair in (parts[:2], parts[-2:]))
    return variants


def _company_variants(name: str) -> list[str]:
    stripped = name.strip()
    bare = _LEGAL_FORMS.sub("", stripped).strip(_QUOTES + " ")
    if bare.lower().startswith("ип ") or not bare:
        return [stripped]
    variants = [stripped, bare] if len(bare) >= 3 else [stripped]
    if stripped.casefold().startswith("ип "):
        variants.extend(_name_variants(bare))
    return variants


def _mask_terms(text: str, terms: Iterable[str], mask: str) -> str:
    for term in sorted({t for t in terms if t}, key=len, reverse=True):
        pattern = r"\s+".join(re.escape(p) for p in term.split())
        text = re.sub(pattern, mask, text, flags=re.IGNORECASE)
    return text


def minimize_client_text(
    text: str | None,
    *,
    person_names: Iterable[str] = (),
    company_names: Iterable[str] = (),
) -> str:
    """Текст клиента для внешнего вызова: маскирует ФИО, названия и длинные числа."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        ch for ch in text if ch.isspace() or not unicodedata.category(ch).startswith("C")
    )
    person_names = [unicodedata.normalize("NFKC", n) for n in person_names]
    company_names = [unicodedata.normalize("NFKC", n) for n in company_names]
    # Название контрагента может отличаться от связанной с заявкой компании.
    text = re.sub(
        r"\b(?:ООО|АО|ПАО|ЗАО|ОАО)\s*[«\"„“][^»\"”\n]+[»\"”]",
        COMPANY_MASK,
        text,
        flags=re.IGNORECASE,
    )
    masked = _mask_terms(
        text, (v for n in company_names for v in _company_variants(n)), COMPANY_MASK
    )
    masked = _mask_terms(masked, (v for n in person_names for v in _name_variants(n)), NAME_MASK)
    return mask_digit_runs(masked)
