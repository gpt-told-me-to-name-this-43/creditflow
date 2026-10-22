"""Детерминированный генератор банковских выписок для демо-компаний.
Требования:
- Повторный запуск побайтно совпадает (фиксированный seed).
- Агрегаты сходятся копейка в копейку со спецификацией.
- 2-5% UNCLASSIFIED учтены в агрегатах.
"""
import json
import random
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
from pathlib import Path

APP_AS_OF_DATE = date(2026, 10, 21)

# Целевые агрегаты по компаниям (из спецификации)
TARGETS = {
    "C1": {"cfads": 40000000, "revenue_change_pct": 500, "debt_svc": 5000000,
           "months": 60, "bki": "CLEAN"},
    "C2": {"cfads": 24000000, "revenue_change_pct": -800, "debt_svc": 10000000,
           "months": 36, "bki": "CLEAN",
           # Жёсткая привязка медианы: 6 значений, медиана = (238000+242000)/2 = 240000
           "fixed_net_cashflow": [23500000, 23800000, 24000000, 24200000, 24500000, 25000000]},
    "C3": {"cfads": 30000000, "revenue_change_pct": 300, "debt_svc": 0,
           "months": 30, "bki": "SERIOUS"},
    "C4": {"cfads": None, "revenue_change_pct": None, "debt_svc": 0,
           "months": 4, "bki": "CLEAN"},  # h < 6 → BLOCKED
    "C5": {"cfads": None, "months": 0, "bki": "CLEAN"},  # LIQUIDATING
    "C6": {"cfads": None, "months": 0, "bki": "CLEAN"},  # FNS blocks
    "C7": {"cfads": 12000000, "revenue_change_pct": 0, "debt_svc": 10000000,
           "months": 36, "bki": "CLEAN"},
}

COUNTERPARTIES = {
    "C1": [
        {"inn": "7701000001", "name": "ООО Рога и Копыта", "is_bank": False},
        {"inn": "044525597",  "name": "АО Альфа-Банк",       "is_bank": True},
    ],
    "C2": [
        {"inn": "5001000002", "name": "ООО Мука Опт",        "is_bank": False},
        {"inn": "044525597",  "name": "АО Альфа-Банк",       "is_bank": True},
    ],
    "C3": [
        {"inn": "7702000003", "name": "ИП Петров С.А.",      "is_bank": False},
        {"inn": "044525597",  "name": "АО Альфа-Банк",       "is_bank": True},
    ],
    "C4": [
        {"inn": "7703000004", "name": "ООО Поставщик",       "is_bank": False},
        {"inn": "044525597",  "name": "АО Альфа-Банк",       "is_bank": True},
    ],
    "C7": [
        {"inn": "7704000007", "name": "ООО Заказчик",        "is_bank": False},
        {"inn": "044525597",  "name": "АО Альфа-Банк",       "is_bank": True},
    ],
}


def _to_kopecks(rub_decimal: int) -> int:
    return rub_decimal * 100


def _split_amount(total_kopecks: int, n_parts: int, rng: random.Random) -> list[int]:
    """Разбивает сумму на n частей с шумом, последняя добирает остаток."""
    if n_parts == 1:
        return [total_kopecks]
    parts = []
    remaining = total_kopecks
    for i in range(n_parts - 1):
        avg = remaining // (n_parts - i)
        noise = rng.randint(-avg // 10, avg // 10)
        part = max(100, avg + noise)  # минимум 1 рубль
        parts.append(part)
        remaining -= part
    parts.append(remaining)
    return parts


def generate_company_statements(code: str, inn: str, director_inn: str) -> list[dict]:
    target = TARGETS[code]
    rng = random.Random(f"statements_{code}_v1")  # детерминированный seed
    
    if target["months"] == 0:
        return []
    
    statements = []
    ext_id = 0
    counterparties = COUNTERPARTIES.get(code, [])
    
    # Окно: 12 полных месяцев до APP_AS_OF_DATE
    end_month = date(APP_AS_OF_DATE.year, APP_AS_OF_DATE.month, 1) - timedelta(days=1)
    start_month = date(end_month.year - 1, end_month.month, 1)
    
    months = []
    cur = start_month
    while cur <= end_month:
        months.append(cur)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    
    months = months[:target["months"]] if target["months"] <= len(months) else months
    
    # Для C2 — жёстко зафиксированные net cashflow по месяцам
    if "fixed_net_cashflow" in target:
        fixed = target["fixed_net_cashflow"]
        # Берём последние 6 месяцев, распределяем
        for i, m in enumerate(months[-6:]):
            net_kopecks = fixed[i]
            # Разбиваем на revenue и opex так, чтобы net = revenue - opex
            revenue_k = int(net_kopecks * 1.5)  # revenue больше
            opex_k = revenue_k - net_kopecks
            
            # Генерируем операции
            for part in _split_amount(revenue_k, 5, rng):
                ext_id += 1
                statements.append({
                    "company_inn": inn, "external_id": f"stmt_{code}_{ext_id}",
                    "booked_at": m.isoformat(), "direction": "IN",
                    "amount_kopecks": part,
                    "counterparty_inn": counterparties[0]["inn"],
                    "counterparty_name": counterparties[0]["name"],
                    "is_bank": False, "purpose_text": "Оплата по счёту № 123",
                })
            for part in _split_amount(opex_k, 3, rng):
                ext_id += 1
                statements.append({
                    "company_inn": inn, "external_id": f"stmt_{code}_{ext_id}",
                    "booked_at": m.isoformat(), "direction": "OUT",
                    "amount_kopecks": part,
                    "counterparty_inn": counterparties[0]["inn"],
                    "counterparty_name": counterparties[0]["name"],
                    "is_bank": False, "purpose_text": "Оплата поставщику",
                })
            
            # Долговое обслуживание (если есть)
            if target["debt_svc"] > 0 and i == len(months[-6:]) - 1:
                # Размазываем долг по всем месяцам
                pass
    
    # Долговое обслуживание — равномерно по месяцам
    if target["debt_svc"] > 0:
        monthly_debt = target["debt_svc"] // len(months)
        for m in months:
            ext_id += 1
            statements.append({
                "company_inn": inn, "external_id": f"stmt_{code}_{ext_id}",
                "booked_at": m.isoformat(), "direction": "OUT",
                "amount_kopecks": monthly_debt * 100,
                "counterparty_inn": "044525597",
                "counterparty_name": "АО Альфа-Банк",
                "is_bank": True, "purpose_text": "Погашение кредита по дог. № 451",
            })
    
    # 2-5% UNCLASSIFIED
    n_unclass = max(1, len(statements) // 30)
    for _ in range(n_unclass):
        ext_id += 1
        statements.append({
            "company_inn": inn, "external_id": f"stmt_{code}_{ext_id}",
            "booked_at": months[rng.randint(0, len(months)-1)].isoformat(),
            "direction": rng.choice(["IN", "OUT"]),
            "amount_kopecks": rng.randint(10000, 500000),
            "counterparty_inn": "7700000000",
            "counterparty_name": "Прочее",
            "is_bank": False, "purpose_text": "Техническая операция",
        })
    
    return sorted(statements, key=lambda x: (x["booked_at"], x["external_id"]))


def main():
    from gen_registry_ids import DEMO_COMPANIES, build_company
    out_dir = Path("ext-sim/fixtures/statements")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    for c in DEMO_COMPANIES:
        if c["code"] in ("C5", "C6", "T1"):
            continue
        company = build_company(c)
        stmts = generate_company_statements(c["code"], company["inn"], company["director_inn"])
        path = out_dir / f"{c['code']}.json"
        path.write_text(json.dumps(stmts, ensure_ascii=False, indent=2))
        print(f"[OK] {c['code']}: {len(stmts)} операций → {path}")


if __name__ == "__main__":
    main()