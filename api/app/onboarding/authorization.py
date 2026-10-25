"""Полномочия заявителя (#5, design.md §3.3): подать заявку может только руководитель
юрлица по ЕГРЮЛ или сам ИП по ЕГРИП. Сверяются ИНН физлица и нормализованное полное ФИО.

Чистые функции: их же вызывает Submit (#7) для повторной проверки (стоп-фактор
`APPLICANT_NOT_AUTHORIZED`).
"""

import unicodedata
from typing import Protocol

from app.extsim_client.dto import EgripEntrepreneur, EgrulCompany, RegistryRecord


class Applicant(Protocol):
    @property
    def full_name(self) -> str: ...

    @property
    def person_inn(self) -> str | None: ...


def normalize_full_name(s: str) -> str:
    """NFC → `ё→е` → casefold → схлопывание пробелов (и обрезка по краям)."""
    text = unicodedata.normalize("NFC", s).replace("ё", "е").replace("Ё", "Е")
    return " ".join(text.casefold().split())


def is_authorized_applicant(registry_record: RegistryRecord, user: Applicant) -> bool:
    if not user.person_inn:
        return False
    if isinstance(registry_record, EgrulCompany):
        inn, full_name = registry_record.director.inn, registry_record.director.full_name
    elif isinstance(registry_record, EgripEntrepreneur):
        inn, full_name = registry_record.inn, registry_record.full_name
    else:
        return False
    return inn == user.person_inn and normalize_full_name(full_name) == normalize_full_name(
        user.full_name
    )
