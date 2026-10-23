"""Выписки ext-sim для демо-компаний (design.md §3.4, issue #6).

Запуск из корня репозитория после `gen_registry_ids.py`: `python scripts/gen_statements.py`.

Порядок «сначала точные агрегаты, потом случайная разбивка»:
1. Для каждого месяца окна задаются целевые суммы в копейках: выручка (revenue),
   операционные расходы (opex = revenue − net), обслуживание долга (debt_svc).
2. Каждая сумма делится на категории (зарплата, аренда, налог, поставщики, 2–5%
   UNCLASSIFIED в opex; эквайринг и оплаты покупателей в revenue), затем на операции
   через `random.Random(seed)`; последняя операция добирает остаток — сумма сходится
   до копейки.
3. Шум, который по правилам категоризации НЕ входит в агрегаты, добавляется отдельно:
   OWN_TRANSFER (контрагент = сама компания), LOAN_PROCEEDS (выдача кредита банком),
   UNCLASSIFIED IN (не выручка).

Назначения платежей подобраны так, чтобы правила `categorization-v1.yaml` дали
именно задуманную категорию; это проверяет golden-тест.

Результат — `ext-sim/fixtures/<inn>/statement.json` в формате `fixtures/README.md`.
Повторный запуск побайтно совпадает (seed фиксирован, float не используется) — CI
проверяет это через `git diff --exit-code ext-sim/fixtures`.
"""

import random
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gen_registry_ids import (
    APP_AS_OF_DATE,
    DEMO_COMPANIES,
    FIXTURES_DIR,
    DemoCompany,
    inn_legal,
    write_json,
)

RUB = 100  # копеек в рубле
SEED_VERSION = "v1"  # смена схемы генерации → новый seed → новые эталоны


def window_months(as_of: date) -> list[date]:
    """12 полных календарных месяцев до месяца as_of: для 2026-10-21 → 2025-10 … 2026-09."""
    first = as_of.year * 12 + as_of.month - 1 - 12
    return [date((first + i) // 12, (first + i) % 12 + 1, 1) for i in range(12)]


@dataclass(frozen=True)
class StatementSpec:
    """Целевые помесячные агрегаты в рублях; списки — по 12 месяцам окна, старые → новые.

    Месяцы до начала истории (history_months) не содержат операций вовсе: так
    FeatureBuilder получает h = history_months.
    """

    revenue: tuple[int, ...]
    net: tuple[int, ...]  # revenue − opex
    debt_svc: int = 0  # ежемесячный платёж по кредитам в выписке
    history_months: int = 12


def _flat(value: int) -> tuple[int, ...]:
    return (value,) * 12


def _halves(prev: int, last: int) -> tuple[int, ...]:
    return (prev,) * 6 + (last,) * 6


# Числа взяты из таблицы демо-компаний #6. Проверка формул (k = 6 при h = 12):
#   C1: выручка 1 000 000 → 1 050 000 (+5,00%), net 400 000, долг 50 000;
#   C2: 1 000 000 → 920 000 (−8,00%); net за последние 6 мес. — 230…250 тыс.,
#       отсортированные средние элементы 238 000 и 242 000 → медиана ровно 240 000;
#   C3: 800 000 → 824 000 (+3,00%), net 300 000, долга нет;
#   C4: история 4 месяца → h = 4 < 6 → ACCOUNT_HISTORY_INSUFFICIENT;
#   C7: выручка без изменений (0,00%), net 120 000, долг 100 000.
# C5, C6, T1 — обычная история: их ветку задают реестр, ФНС и fail_mode.
SPECS: dict[str, StatementSpec] = {
    "C1": StatementSpec(_halves(1_000_000, 1_050_000), _flat(400_000), debt_svc=50_000),
    "C2": StatementSpec(
        _halves(1_000_000, 920_000),
        # порядок намеренно не отсортирован: медиана не должна зависеть от порядка
        (240_000,) * 6 + (238_000, 250_000, 230_000, 242_000, 235_000, 245_000),
        debt_svc=100_000,
    ),
    "C3": StatementSpec(_halves(800_000, 824_000), _flat(300_000)),
    "C4": StatementSpec(_flat(300_000), _flat(50_000), history_months=4),
    "C5": StatementSpec(_flat(500_000), _flat(100_000)),
    "C6": StatementSpec(_flat(500_000), _flat(100_000)),
    "C7": StatementSpec(_flat(600_000), _flat(120_000), debt_svc=100_000),
    "T1": StatementSpec(_flat(500_000), _flat(100_000)),
}

# Доли opex по категориям, в процентах (целые — без float). Остаток уходит поставщикам.
OPEX_SHARES_PCT = {"SALARY": 30, "RENT": 10, "TAX": 10, "UNCLASSIFIED": 3}
ACQUIRING_SHARE_PCT = 15  # доля выручки через эквайринг; остальное — оплаты покупателей


@dataclass(frozen=True)
class Party:
    inn: str | None
    name: str
    is_bank: bool = False


def _party(base5: str, name: str, *, is_bank: bool = False) -> Party:
    # Синтетический ИНН контрагента: регион 00, инспекция 98, корректная контрольная цифра.
    return Party(inn_legal("0098" + base5), name, is_bank)


BANK = _party("00001", "АО «Демо-Банк»", is_bank=True)  # не БИК: валидный 10-значный ИНН
TAX_AUTHORITY = _party("00002", "УФК по г. Москве (ИФНС № 99)")
LANDLORD = _party("00003", "ООО «Аренда-Демо»")
STAFF = Party(None, "Сотрудники (зарплатный реестр)")  # inn = null допустим по контракту


def _pool(code: str, kind: str, n: int) -> list[Party]:
    offset = {"C1": 10, "C2": 20, "C3": 30, "C4": 40, "C5": 50, "C6": 60, "C7": 70, "T1": 90}[code]
    base = 0 if kind == "customer" else 5
    label = "Покупатель" if kind == "customer" else "Поставщик"
    return [_party(f"{offset + base + i:05d}", f"ООО «{label} {code}-{i + 1}»") for i in range(n)]


def split(total: int, parts: int, rng: random.Random) -> list[int]:
    """Разбивает `total` копеек на `parts` положительных частей; последняя добирает остаток.

    Веса — целые 80…120: части отличаются на ±20%, сумма совпадает до копейки.
    """
    if total <= 0:
        return []
    parts = max(1, min(parts, total // (1_000 * RUB)))  # операция не меньше ~1 000 ₽
    weights = [rng.randint(80, 120) for _ in range(parts)]
    w_sum = sum(weights)
    chunks = [total * w // w_sum for w in weights[:-1]]
    chunks.append(total - sum(chunks))
    assert all(c > 0 for c in chunks) and sum(chunks) == total
    return chunks


def _pct(amount: int, pct: int) -> int:
    return amount * pct // 100


class _Builder:
    def __init__(self, company: DemoCompany, rng: random.Random) -> None:
        self.company = company
        self.rng = rng
        self.rows: list[tuple[date, int, dict[str, Any]]] = []

    def add(self, month: date, direction: str, kopecks: int, party: Party, purpose: str) -> None:
        day = self.rng.randint(1, 28)  # 28 — есть в любом месяце
        tx = {
            "direction": direction,
            "amount_rub": f"{kopecks // RUB}.{kopecks % RUB:02d}",
            "counterparty": {"inn": party.inn, "name": party.name, "is_bank": party.is_bank},
            "purpose": purpose,
        }
        # второй ключ сортировки — порядок добавления: стабильный и детерминированный
        self.rows.append((month.replace(day=day), len(self.rows), tx))

    def transactions(self) -> list[dict[str, Any]]:
        out = []
        for seq, (booked_at, _, tx) in enumerate(sorted(self.rows, key=lambda r: r[:2]), 1):
            # external_id стабилен между перегенерациями: по нему api делает upsert
            out.append(
                {
                    "external_id": f"{self.company.inn}-{seq:06d}",
                    "booked_at": booked_at.isoformat(),
                    **tx,
                }
            )
        return out


def generate(company: DemoCompany, spec: StatementSpec) -> dict[str, Any]:
    rng = random.Random(f"statements:{company.code}:{SEED_VERSION}")
    b = _Builder(company, rng)
    customers, suppliers = _pool(company.code, "customer", 3), _pool(company.code, "supplier", 2)
    own = Party(company.inn, f"{company.name} (счёт в другом банке)")
    months = window_months(APP_AS_OF_DATE)
    active = months[12 - spec.history_months :]

    for m in active:
        i = months.index(m)
        revenue, net = spec.revenue[i] * RUB, spec.net[i] * RUB
        opex = revenue - net
        assert opex > 0, (company.code, m)
        stamp = m.strftime("%m.%Y")

        # --- revenue: ACQUIRING (IN от банка ~ «эквайринг») + CUSTOMER_PAYMENT (IN от ЮЛ ~ «оплат»)
        acquiring = _pct(revenue, ACQUIRING_SHARE_PCT)
        for part in split(acquiring, 2, rng):
            b.add(m, "IN", part, BANK, "Зачисление средств по операциям эквайринга")
        for n, part in enumerate(split(revenue - acquiring, 6, rng), 1):
            b.add(m, "IN", part, rng.choice(customers), f"Оплата по счёту № {n} от 01.{stamp}")

        # --- opex: каждая категория со своим ключевым словом из правила 4/6
        shares = {cat: _pct(opex, pct) for cat, pct in OPEX_SHARES_PCT.items()}
        for part in split(shares["SALARY"], 2, rng):
            b.add(m, "OUT", part, STAFF, f"Перечисление заработной платы за {stamp}")
        b.add(m, "OUT", shares["RENT"], LANDLORD, f"Арендная плата по договору № 15 за {stamp}")
        b.add(m, "OUT", shares["TAX"], TAX_AUTHORITY, "Налог по УСН. КБК 18210501011011000110")
        # UNCLASSIFIED OUT: ни одно правило не срабатывает → консервативно в opex (design §3.4)
        b.add(m, "OUT", shares["UNCLASSIFIED"], suppliers[0], "Перевод по договору № 7-П")
        supplier_total = opex - sum(shares.values())
        for part in split(supplier_total, 4, rng):
            b.add(m, "OUT", part, rng.choice(suppliers), "Оплата поставки по счёту № 31")

        # --- debt_svc: OUT банку ~ «погашени»
        if spec.debt_svc:
            b.add(
                m, "OUT", spec.debt_svc * RUB, BANK, "Погашение кредита и процентов по дог. № 451"
            )

        # --- шум вне агрегатов
        b.add(m, "IN", 50_000 * RUB, own, "Перевод собственных средств между счетами")
        b.add(m, "OUT", 50_000 * RUB, own, "Перевод собственных средств между счетами")
        b.add(m, "IN", rng.randint(5_000, 15_000) * RUB, suppliers[1], "Возврат по договору № 7-П")

    if spec.debt_svc:  # выдача кредита — не выручка (правило 3)
        b.add(active[0], "IN", 1_000_000 * RUB, BANK, "Выдача кредита по договору № 451")

    return {"account_masked": f"40702 •••• {company.inn[-4:]}", "transactions": b.transactions()}


def main() -> None:
    for company in DEMO_COMPANIES:
        statement = generate(company, SPECS[company.code])
        path = FIXTURES_DIR / company.inn / "statement.json"
        write_json(path, statement)
        print(f"[OK] {company.code} {company.inn}: {len(statement['transactions'])} операций")


if __name__ == "__main__":
    main()
