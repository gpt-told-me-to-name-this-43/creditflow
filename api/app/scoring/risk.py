from decimal import Decimal
from .money import to_decimal, round_money, floor_to_10k

class RiskEngine:
    def __init__(self, rate_pct: Decimal, max_amount: Decimal, min_amount: Decimal):
        self.rate_pct = to_decimal(rate_pct)
        self.max_amount = to_decimal(max_amount)
        self.min_amount = to_decimal(min_amount)

    def calculate_annuity_factor(self, n: int) -> Decimal:
        r = self.rate_pct / Decimal("1200")
        if r == 0:
            return Decimal("1") / to_decimal(n)
        return r / (Decimal("1") - (Decimal("1") + r) ** (-n))

    def calculate_payment(self, amount: Decimal, n: int) -> Decimal:
        A = self.calculate_annuity_factor(n)
        return amount * A

    def calculate_dscr(self, cfads: Decimal, existing_debt: Decimal, payment: Decimal) -> Decimal:
        denominator = existing_debt + payment
        if denominator <= 0:
            raise ValueError("Debt service + payment must be > 0")
        return cfads / denominator

    def calculate_limit(self, cfads: Decimal, existing_debt: Decimal, A: Decimal) -> Decimal | None:
        p_max = max(Decimal("0"), (cfads / Decimal("1.25")) - existing_debt)
        
        raw_limit = min(p_max / A, self.max_amount)
        limit = floor_to_10k(raw_limit)
        
        if limit < self.min_amount:
            return None
        return limit

    def calculate_score(self, dscr_raw: Decimal, bki_status: str, revenue_change_pct: Decimal, age_months: int) -> dict:
        points = {}
        
        if dscr_raw >= Decimal("1.50"): points['dscr'] = 40
        elif dscr_raw >= Decimal("1.25"): points['dscr'] = 30
        elif dscr_raw >= Decimal("1.00"): points['dscr'] = 10
        else: points['dscr'] = 0

        bki_map = {'CLEAN': 30, 'UNKNOWN': 15, 'MINOR': 10, 'SERIOUS': 0}
        points['bki'] = bki_map.get(bki_status, 0)

        if revenue_change_pct >= Decimal("0"): points['revenue'] = 15
        elif revenue_change_pct >= Decimal("-15"): points['revenue'] = 8
        else: points['revenue'] = 0

        if age_months >= 24: points['age'] = 15
        elif age_months >= 12: points['age'] = 8
        else: points['age'] = 0

        total = sum(points.values())

        if total >= 80: level = 'LOW'
        elif total >= 60: level = 'MODERATE'
        elif total >= 40: level = 'HIGH'
        else: level = 'VERY_HIGH'
        
        if dscr_raw < Decimal("1.00") and level in ['LOW', 'MODERATE']:
            level = 'HIGH'

        return {'score': total, 'risk_level': level, 'factor_points': points}