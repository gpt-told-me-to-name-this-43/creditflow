"""Реестровые фикстуры ext-sim для демо-компаний C1–C7 и T1 (issue #6).

Запуск из корня репозитория: `python scripts/gen_registry_ids.py`.

Пишет в `ext-sim/fixtures/<inn>/` файлы `egrul.json` | `egrip.json`, `fns.json`,
`bki.json` и (для T1) `meta.json` строго по контракту `ext-sim/fixtures/README.md`:
ext-sim валидирует их своими Pydantic-схемами при старте (`extra="forbid"`), поэтому
здесь нет ни одного поля сверх контракта.

Синтетика: код региона `00` не встречается в настоящих ИНН/ОГРН, поэтому совпадение
с реальной организацией исключено (тот же приём, что у образца `0099000014`).
Повторный запуск побайтно совпадает: нет случайности, порядок ключей фиксирован,
кодировка всегда UTF-8 независимо от ОС.
"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

APP_AS_OF_DATE = date(2026, 10, 21)
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "ext-sim" / "fixtures"
# Момент проверки ФНС фиксирован, а не `datetime.now()`: иначе файл меняется на каждом запуске.
FNS_CHECKED_AT = "2026-10-21T09:00:00Z"

_INN10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check_digit(digits: str, weights: tuple[int, ...]) -> str:
    # strict=True: длина базы и весов обязана совпадать, иначе это ошибка вызова.
    return str(sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 % 10)


def inn_legal(base9: str) -> str:
    """10-значный ИНН ЮЛ: 9 цифр + контрольная."""
    assert len(base9) == 9 and base9.isdigit(), base9
    return base9 + _check_digit(base9, _INN10_WEIGHTS)


def inn_person(base10: str) -> str:
    """12-значный ИНН физлица/ИП: 10 цифр + две контрольные."""
    assert len(base10) == 10 and base10.isdigit(), base10
    c1 = _check_digit(base10, _INN12_WEIGHTS_1)
    return base10 + c1 + _check_digit(base10 + c1, _INN12_WEIGHTS_2)


def ogrn(base12: str) -> str:
    """ОГРН ЮЛ: первые 12 цифр mod 11 mod 10."""
    assert len(base12) == 12 and base12.isdigit(), base12
    return base12 + str(int(base12) % 11 % 10)


def ogrnip(base14: str) -> str:
    """ОГРНИП: первые 14 цифр mod 13 mod 10."""
    assert len(base14) == 14 and base14.isdigit(), base14
    return base14 + str(int(base14) % 13 % 10)


def months_before(as_of: date, months: int) -> date:
    """Дата ровно `months` полных месяцев назад (то же число; для 29–31 — конец месяца)."""
    y, m = divmod(as_of.year * 12 + as_of.month - 1 - months, 12)
    for day in (as_of.day, 30, 29, 28):
        try:
            return date(y, m + 1, day)
        except ValueError:
            continue
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class Obligation:
    creditor_name: str
    monthly_payment_rub: int
    outstanding_rub: int


@dataclass(frozen=True)
class DemoCompany:
    code: str
    legal_form: Literal["LLC", "IE"]
    name: str  # для ЮЛ — название; в ЕГРИП у ИП хранится только ФИО
    director_full_name: str
    # Базы без контрольных цифр. ИНН ИП = ИНН физлица, поэтому у ИП inn_base не нужен.
    inn_base: str  # 9 цифр, только LLC
    person_base: str  # 10 цифр: ИНН руководителя ЮЛ или самого ИП
    ogrn_base: str  # 12 цифр (ОГРН) или 14 (ОГРНИП)
    okved: str
    age_months: int  # возраст бизнеса на APP_AS_OF_DATE — из спецификации #6
    status: Literal["ACTIVE", "LIQUIDATING", "LIQUIDATED"] = "ACTIVE"
    bankruptcy: bool = False
    active_account_blocks: int = 0
    bki_status: Literal["CLEAN", "UNKNOWN", "MINOR", "SERIOUS"] = "CLEAN"
    obligations: tuple[Obligation, ...] = ()
    fail_mode: str | None = None

    @property
    def director_inn(self) -> str:
        return inn_person(self.person_base)

    @property
    def inn(self) -> str:
        return inn_legal(self.inn_base) if self.legal_form == "LLC" else self.director_inn

    @property
    def registered_at(self) -> date:
        return months_before(APP_AS_OF_DATE, self.age_months)


_BANK = "АО «Демо-Банк»"

# Единственный источник истины для реестровой части демо-компаний.
# Ожидаемые результаты расчёта живут в docs/demo-data.md и в golden-тесте, а не здесь:
# эталон не должен «подстраиваться» под генератор.
# fmt: off
DEMO_COMPANIES: tuple[DemoCompany, ...] = (
    DemoCompany(code="C1", legal_form="LLC", name="ООО «ТехСервис»",
                director_full_name="Иванов Пётр Сергеевич",
                inn_base="009901001", person_base="0099010010", ogrn_base="120009901001",
                okved="62.01", age_months=60,
                obligations=(Obligation(_BANK, 50_000, 1_200_000),)),
    DemoCompany(code="C2", legal_form="LLC", name="ООО «Пекарня Плюс»",
                director_full_name="Кузнецова Анна Михайловна",
                inn_base="009902001", person_base="0099020010", ogrn_base="122009902001",
                okved="10.71", age_months=36,
                obligations=(Obligation(_BANK, 100_000, 2_400_000),)),
    # #5 проверяет нормализацию «Соколова Алёна Викторовна» = «соколова  алена викторовна»,
    # поэтому в реестре именно «Алёна» — с «ё».
    DemoCompany(code="C3", legal_form="IE", name="ИП Соколова А. В.",
                director_full_name="Соколова Алёна Викторовна",
                inn_base="", person_base="0099030010", ogrn_base="32300990300001",
                okved="62.02", age_months=30, bki_status="SERIOUS"),
    DemoCompany(code="C4", legal_form="LLC", name="ООО «Новый Старт»",
                director_full_name="Новиков Станислав Олегович",
                inn_base="009904001", person_base="0099040010", ogrn_base="126009904001",
                okved="46.39", age_months=4),
    DemoCompany(code="C5", legal_form="LLC", name="ООО «Вектор»",
                director_full_name="Векторов Андрей Игоревич",
                inn_base="009905001", person_base="0099050010", ogrn_base="119009905001",
                okved="46.90", age_months=91, status="LIQUIDATING"),
    DemoCompany(code="C6", legal_form="LLC", name="ООО «Склад-М»",
                director_full_name="Складов Михаил Дмитриевич",
                inn_base="009906001", person_base="0099060010", ogrn_base="120009906001",
                okved="52.10", age_months=73, active_account_blocks=2),
    DemoCompany(code="C7", legal_form="IE", name="ИП Орлов Д. С.",
                director_full_name="Орлов Дмитрий Степанович",
                inn_base="", person_base="0099070010", ogrn_base="32300990700001",
                okved="49.41", age_months=36,
                obligations=(Obligation(_BANK, 100_000, 3_000_000),)),
    DemoCompany(code="T1", legal_form="LLC", name="ООО «Тест Сбой»",
                director_full_name="Тестов Тест Тестович",
                inn_base="009999001", person_base="0099990010", ogrn_base="122009999001",
                okved="62.01", age_months=48, fail_mode="bki_timeout"),
)
# fmt: on


def _money(rub: int) -> str:
    # Контракт ext-sim: деньги — строка с двумя знаками ("45000.00"), float запрещён.
    return f"{rub}.00"


def registry_record(c: DemoCompany) -> tuple[str, dict[str, Any]]:
    """(имя файла, содержимое) — ровно поля EgrulCompany / EgripEntrepreneur."""
    if c.legal_form == "LLC":
        return "egrul.json", {
            "inn": c.inn,
            "ogrn": ogrn(c.ogrn_base),
            "name": c.name,
            "status": c.status,
            "registered_at": c.registered_at.isoformat(),
            "okved_main": c.okved,
            # ИНН руководителя — ИНН физлица, 12 цифр (Director.inn: ^\d{12}$).
            "director": {"full_name": c.director_full_name, "inn": c.director_inn},
        }
    return "egrip.json", {
        "inn": c.inn,
        "ogrnip": ogrnip(c.ogrn_base),
        "full_name": c.director_full_name,
        "status": c.status,
        "registered_at": c.registered_at.isoformat(),
        "okved_main": c.okved,
    }


def fns_record(c: DemoCompany) -> dict[str, Any]:
    return {
        "bankruptcy": c.bankruptcy,
        "active_account_blocks": c.active_account_blocks,
        "checked_at": FNS_CHECKED_AT,
    }


def bki_record(c: DemoCompany) -> dict[str, Any]:
    # report_id не хранится: ext-sim вычисляет его из ИНН и consent_id (UUID v5).
    return {
        "summary_status": c.bki_status,
        "monthly_payments_total_rub": _money(sum(o.monthly_payment_rub for o in c.obligations)),
        "obligations": [
            {
                "creditor_name": o.creditor_name,
                "monthly_payment_rub": _money(o.monthly_payment_rub),
                "outstanding_rub": _money(o.outstanding_rub),
            }
            for o in c.obligations
        ],
    }


def write_json(path: Path, data: Any) -> None:
    """Детерминированная запись: всегда UTF-8 и LF, фиксированный отступ, \\n в конце."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    for c in DEMO_COMPANIES:
        company_dir = FIXTURES_DIR / c.inn
        filename, record = registry_record(c)
        write_json(company_dir / filename, record)
        write_json(company_dir / "fns.json", fns_record(c))
        write_json(company_dir / "bki.json", bki_record(c))
        meta = company_dir / "meta.json"
        if c.fail_mode is not None:
            write_json(meta, {"fail_mode": c.fail_mode})
        elif meta.exists():
            meta.unlink()
        print(f"[OK] {c.code} {c.inn}: {filename}, fns.json, bki.json")


if __name__ == "__main__":
    main()
