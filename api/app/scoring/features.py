from decimal import Decimal
from datetime import date, timedelta
from collections import defaultdict
import statistics

# Категории из design.md §3.4
REVENUE_CATS = {"CUSTOMER_PAYMENT", "ACQUIRING"}
OPEX_CATS = {"SUPPLIER", "SALARY", "TAX", "RENT", "CASH_WITHDRAWAL", "OWNER_TRANSFER", "UNCLASSIFIED"}
DEBT_SVC_CATS = {"LOAN_REPAYMENT"}

class FeatureBuilder:
    def __init__(self, as_of_date: date):
        self.as_of_date = as_of_date

    def build(self, transactions: list[dict], business_age_months: int, bki_monthly_payments: Decimal) -> dict:
        """
        transactions: список dict с полями: booked_at (str 'YYYY-MM-DD'), direction ('IN'/'OUT'), 
                      amount_rub (Decimal), category (str)
        """
        end_month = date(self.as_of_date.year, self.as_of_date.month, 1) - timedelta(days=1)
        start_month = date(end_month.year - 1, end_month.month, 1)
        
        monthly_data = defaultdict(lambda: {"revenue": Decimal("0"), "opex": Decimal("0"), "debt_svc": Decimal("0")})
        
        for tx in transactions:
            tx_date = date.fromisoformat(tx["booked_at"])
            # Попадаем ли в 12-месячное окно?
            if start_month <= tx_date <= end_month:
                month_key = tx_date.replace(day=1)
                amount = Decimal(str(tx["amount_rub"]))
                cat = tx["category"]
                
                if tx["direction"] == "IN" and cat in REVENUE_CATS:
                    monthly_data[month_key]["revenue"] += amount
                elif tx["direction"] == "OUT":
                    if cat in OPEX_CATS:
                        monthly_data[month_key]["opex"] += amount
                    elif cat in DEBT_SVC_CATS:
                        monthly_data[month_key]["debt_svc"] += amount

        sorted_months = sorted(monthly_data.keys())
        h = len(sorted_months) 
        
        # Стоп-фактор: недостаточно истории
        if h < 6:
            return {
                "calculation_status": "SKIPPED",
                "blocking_codes": ["ACCOUNT_HISTORY_INSUFFICIENT"],
                "h": h,
                "cfads_monthly_rub": Decimal("0"),
                "revenue_change_pct": Decimal("0"),
                "existing_debt_payments_rub": bki_monthly_payments,
                "business_age_months": business_age_months,
            }

        # Извлекаем ряды
        revenues = [monthly_data[m]["revenue"] for m in sorted_months]
        opexes = [monthly_data[m]["opex"] for m in sorted_months]
        debt_svcs = [monthly_data[m]["debt_svc"] for m in sorted_months]
        net_cashflows = [r - o for r, o in zip(revenues, opexes)]

        # CFADS: медиана net cashflow за последние min(6, h) мес.
        last_6_net = net_cashflows[-min(6, h):]
        cfads = Decimal(str(statistics.median(last_6_net)))

        # Revenue change: k = floor(h / 2)
        k = h // 2
        if k == 0:
            k = 1 # Защита от деления на ноль, хотя h >= 6 гарантирует k >= 3
        
        sum_prev = sum(revenues[:k])
        sum_last = sum(revenues[-k:])
        
        if sum_prev == Decimal("0"):
            revenue_change_pct = Decimal("0")
        else:
            revenue_change_pct = ((sum_last / sum_prev) - Decimal("1")) * Decimal("100")

        # Existing debt: max(mean за 3 мес, БКИ)
        last_3_debt = debt_svcs[-min(3, h):]
        mean_debt = sum(last_3_debt) / Decimal(len(last_3_debt))
        existing_debt = max(mean_debt, bki_monthly_payments)

        return {
            "calculation_status": "OK",
            "blocking_codes": [],
            "h": h,
            "cfads_monthly_rub": cfads,
            "revenue_change_pct": revenue_change_pct,
            "existing_debt_payments_rub": existing_debt,
            "business_age_months": business_age_months,
            "monthly_series": {
                "revenues": [str(r) for r in revenues],
                "opexes": [str(o) for o in opexes],
            }
        }