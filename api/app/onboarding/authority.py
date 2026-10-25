"""Проверка ИНН и полномочий заявителя (design.md §3.3 «Привязка компании»).

Полномочия: ИНН **и** нормализованное ФИО руководителя (ЕГРЮЛ) или ИП (ЕГРИП) совпадают
с учёткой. Та же проверка повторяется при Submit (стоп-фактор APPLICANT_NOT_AUTHORIZED).
"""

import re
import unicodedata

from app.extsim_client.dto import EgripEntrepreneur, EgrulCompany, RegistryRecord

_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def inn_is_valid(inn: str) -> bool:
    """Формат и контрольные цифры: 10 — ЮЛ, 12 — физлицо/ИП."""
    if not inn.isdigit():
        return False
    if len(inn) == 10:
        return _check_digit(inn, _W10) == int(inn[9])
    if len(inn) == 12:
        return _check_digit(inn, _W11) == int(inn[10]) and _check_digit(inn, _W12) == int(inn[11])
    return False


def normalize_name(name: str) -> str:
    """NFC, ё→е, нижний регистр, схлопнутые пробелы."""
    text = unicodedata.normalize("NFC", name).lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def applicant_of(record: RegistryRecord) -> tuple[str, str]:
    """(ИНН, ФИО) лица, которое может подать заявку: руководитель ЮЛ или сам ИП."""
    if isinstance(record, EgrulCompany):
        return record.director.inn, record.director.full_name
    assert isinstance(record, EgripEntrepreneur)
    return record.inn, record.full_name


def is_authorized(record: RegistryRecord, person_inn: str | None, full_name: str) -> bool:
    inn, name = applicant_of(record)
    return person_inn == inn and normalize_name(full_name) == normalize_name(name)


def company_fields(record: RegistryRecord) -> dict[str, object]:
    if isinstance(record, EgrulCompany):
        legal_form, name = "LLC", record.name
    else:
        legal_form, name = "IE", f"ИП {record.full_name}"
    return {
        "inn": record.inn,
        "legal_form": legal_form,
        "name": name,
        "okved_main": record.okved_main,
        "registered_at": record.registered_at,
    }
