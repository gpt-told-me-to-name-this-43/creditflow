"""Генерация валидных ИНН/ОГРН с корректными контрольными суммами"""

def _checksum(digits: list[int], coefficients: list[int]) -> int:
    return sum(d * c for d, c in zip(digits, coefficients)) % 11 % 10


def gen_inn_ll(base9: str) -> str:
    """10-значный ИНН для ЮЛ. base9 — любые 9 цифр."""
    assert len(base9) == 9 and base9.isdigit()
    digits = [int(d) for d in base9]
    coefs = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    check = _checksum(digits, coefs)
    return base9 + str(check)


def gen_inn_ie(base10: str) -> str:
    """12-значный ИНН для ИП. base10 — любые 10 цифр."""
    assert len(base10) == 10 and base10.isdigit()
    digits = [int(d) for d in base10]
    coefs1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    coefs2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
    c1 = _checksum(digits, coefs1)
    c2 = _checksum(digits + [c1], coefs2)
    return base10 + str(c1) + str(c2)


def gen_ogrn_ll(base12: str) -> str:
    """13-значный ОГРН для ЮЛ."""
    assert len(base12) == 12 and base12.isdigit()
    n = int(base12)
    c = n % 11 % 10
    return base12 + str(c)


def gen_ogrn_ie(base14: str) -> str:
    """15-значный ОГРНИП для ИП."""
    assert len(base14) == 14 and base14.isdigit()
    n = int(base14)
    c = n % 13 % 10
    return base14 + str(c)


DEMO_COMPANIES = [
    # C1: ТехСервис — идеальная, ELIGIBLE
    {
        "code": "C1", "name": 'ООО "ТехСервис"', "legal_form": "LLC",
        "inn_base9": "779901001", "ogrn_base12": "126770000001",
        "okved": "62.01", "registered_at": "2022-04-15",
        "director": {"full_name": "Иванов Петр Сергеевич", "person_inn_base10": "7799010001"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "CLEAN", "monthly_payments_bki": 50000,
        "scenario": "investment", "amount": 2000000, "term": 36,
        "expected": {"action": "ELIGIBLE_FOR_MANAGER_REVIEW", "score": 100, "dscr_display": "3.11",
                     "limit": 5000000, "risk_level": "LOW"},
    },
    # C2: Пекарня Плюс — COUNTER_OFFER
    {
        "code": "C2", "name": 'ООО "Пекарня Плюс"', "legal_form": "LLC",
        "inn_base9": "502202002", "ogrn_base12": "125500000002",
        "okved": "10.71", "registered_at": "2023-01-10",
        "director": {"full_name": "Кузнецова Анна Михайловна", "person_inn_base10": "5022020002"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "CLEAN", "monthly_payments_bki": 100000,
        "scenario": "investment", "amount": 3000000, "term": 36,
        "expected": {"action": "COUNTER_OFFER_CANDIDATE", "score": 63, "dscr_display": "1.10",
                     "limit": 2340000, "risk_level": "MODERATE"},
    },
    # C3: ИП Соколова — MANUAL_REVIEW по R2 (SERIOUS БКИ)
    {
        "code": "C3", "name": "ИП Соколова А.В.", "legal_form": "IE",
        "inn_base10": "7722330003", "ogrn_base14": "32577000000003",
        "okved": "62.02", "registered_at": "2023-04-20",
        "director": {"full_name": "Соколова Алиса Владимировна", "person_inn_base10": "7722330003"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "SERIOUS", "monthly_payments_bki": 0,
        "scenario": "working_capital", "amount": 800000, "term": 12,
        "expected": {"action": "MANUAL_REVIEW", "score": 70, "dscr_display": "3.96",
                     "limit": 800000, "risk_level": "MODERATE"},
    },
    # C4: Новый Старт — BLOCKED (история 4 мес)
    {
        "code": "C4", "name": 'ООО "Новый Старт"', "legal_form": "LLC",
        "inn_base9": "771104004", "ogrn_base12": "126770000004",
        "okved": "46.39", "registered_at": "2026-06-01",  # 4 месяца до APP_AS_OF_DATE=2026-10-21
        "director": {"full_name": "Новиков Станислав Олегович", "person_inn_base10": "7711040004"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "CLEAN", "monthly_payments_bki": 0,
        "scenario": "investment", "amount": 500000, "term": 24,
        "expected": {"action": "BLOCKED_BY_RULE", "blocking_codes": ["ACCOUNT_HISTORY_INSUFFICIENT"]},
    },
    # C5: Вектор — BLOCKED (LIQUIDATING)
    {
        "code": "C5", "name": 'ООО "Вектор"', "legal_form": "LLC",
        "inn_base9": "773305005", "ogrn_base12": "120770000005",
        "okved": "46.90", "registered_at": "2019-03-14",
        "director": {"full_name": "Векторов Андрей Игоревич", "person_inn_base10": "7733050005"},
        "status": "LIQUIDATING", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "CLEAN", "monthly_payments_bki": 0,
        "scenario": "working_capital", "amount": 1000000, "term": 12,
        "expected": {"action": "BLOCKED_BY_RULE", "blocking_codes": ["COMPANY_INACTIVE"]},
    },
    # C6: Склад-М — BLOCKED (ФНС блокировки)
    {
        "code": "C6", "name": 'ООО "Склад-М"', "legal_form": "LLC",
        "inn_base9": "774406006", "ogrn_base12": "118770000006",
        "okved": "52.10", "registered_at": "2020-09-01",
        "director": {"full_name": "Складов Михаил Дмитриевич", "person_inn_base10": "7744060006"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 2,
        "bki_status": "CLEAN", "monthly_payments_bki": 0,
        "scenario": "working_capital", "amount": 1500000, "term": 18,
        "expected": {"action": "BLOCKED_BY_RULE", "blocking_codes": ["ACCOUNT_BLOCKED_BY_FNS"]},
    },
    # C7: ИП Орлов — MANUAL_REVIEW по R5 (высокая нагрузка, лимит null)
    {
        "code": "C7", "name": "ИП Орлов Д.С.", "legal_form": "IE",
        "inn_base10": "7755070007", "ogrn_base14": "32177000000007",
        "okved": "49.41", "registered_at": "2023-02-10",
        "director": {"full_name": "Орлов Дмитрий Степанович", "person_inn_base10": "7755070007"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "CLEAN", "monthly_payments_bki": 100000,
        "scenario": "investment", "amount": 1000000, "term": 36,
        "expected": {"action": "MANUAL_REVIEW", "score": 60, "dscr_display": "0.86",
                     "limit": None, "risk_level": "HIGH"},
    },
    # T1: Тестовый сбой
    {
        "code": "T1", "name": 'ООО "Тест Сбой"', "legal_form": "LLC",
        "inn_base9": "776608008", "ogrn_base12": "124770000008",
        "okved": "62.01", "registered_at": "2022-01-01",
        "director": {"full_name": "Тестов Тест Тестович", "person_inn_base10": "7766080008"},
        "status": "ACTIVE", "bankruptcy": False, "fns_blocks": 0,
        "bki_status": "CLEAN", "monthly_payments_bki": 0,
        "scenario": "investment", "amount": 1000000, "term": 24,
        "expected": {"fail_mode": "bki_timeout"},
    },
]


def build_company(c: dict) -> dict:
    """Собирает компанию с вычисленными ИНН/ОГРН."""
    out = {k: v for k, v in c.items() if k not in ("inn_base9", "inn_base10", "ogrn_base12", "ogrn_base14", "director")}
    if c["legal_form"] == "LLC":
        out["inn"] = gen_inn_ll(c["inn_base9"])
        out["ogrn"] = gen_ogrn_ll(c["ogrn_base12"])
    else:
        out["inn"] = gen_inn_ie(c["inn_base10"])
        out["ogrn"] = gen_ogrn_ie(c["ogrn_base14"])
    out["director_inn"] = (gen_inn_ie(c["director"]["person_inn_base10"])
                           if c["legal_form"] == "IE"
                           else gen_inn_ll(c["director"]["person_inn_base10"][:9]))
    out["director_full_name"] = c["director"]["full_name"]
    return out





def generate_ext_sim_fixtures():
    """Генерирует полную структуру фикстур для ext-sim."""
    import json
    from pathlib import Path
    
    fixtures_dir = Path("ext-sim/fixtures")
    
    for c in DEMO_COMPANIES:
        if c["code"] == "T1":
            continue
            
        company = build_company(c)
        inn = company["inn"]
        company_dir = fixtures_dir / inn
        company_dir.mkdir(parents=True, exist_ok=True)
        
        # ЕГРЮЛ/ЕГРИП
        if c["legal_form"] == "LLC":
            egrul = {
                "inn": inn,
                "ogrn": company["ogrn"],
                "name": c["name"],
                "legal_form": "LLC",
                "status": c["status"],
                "okved_main": c["okved"],
                "registered_at": c["registered_at"],
                "director": {
                    "full_name": c["director"]["full_name"],
                    "inn": company["director_inn"]
                }
            }
            (company_dir / "egrul.json").write_text(json.dumps(egrul, ensure_ascii=False, indent=2))
        else:
            egrip = {
                "inn": inn,
                "ogrn": company["ogrn"],
                "name": c["name"],
                "legal_form": "IE",
                "status": c["status"],
                "okved_main": c["okved"],
                "registered_at": c["registered_at"],
                "entrepreneur": {
                    "full_name": c["director"]["full_name"],
                    "inn": inn
                }
            }
            (company_dir / "egrip.json").write_text(json.dumps(egrip, ensure_ascii=False, indent=2))
        
        # ФНС
        fns = {
            "inn": inn,
            "bankruptcy": c.get("bankruptcy", False),
            "fns_blocks": c.get("fns_blocks", 0)
        }
        (company_dir / "fns.json").write_text(json.dumps(fns, ensure_ascii=False, indent=2))
        
        # БКИ
        bki = {
            "inn": inn,
            "summary_status": c["bki_status"],
            "monthly_payments_total_rub": c.get("monthly_payments_bki", 0)
        }
        (company_dir / "bki.json").write_text(json.dumps(bki, ensure_ascii=False, indent=2))
        
        print(f"[OK] {c['code']} (ИНН {inn}): фикстуры ext-sim созданы")


if __name__ == "__main__":
    import json
    for c in DEMO_COMPANIES:
        print(json.dumps(build_company(c), ensure_ascii=False, indent=2))
    
    print("\n--- Генерация фикстур ext-sim ---")
    generate_ext_sim_fixtures()