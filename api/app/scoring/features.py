from collections import defaultdict
from datetime import date
from decimal import Decimal

REVENUE_CATS = {"CUSTOMER_PAYMENT", "ACQUIRING"}
OPEX_CATS = {
    "SUPPLIER",
    "SALARY",
    "TAX",
    "RENT",
    "CASH_WITHDRAWAL",
    "OWNER_TRANSFER",
    "UNCLASSIFIED",
}
DEBT_SVC_CATS = {"LOAN_REPAYMENT"}


class FeatureBuilder:
    def __init__(self, as_of_date: date):
        self.as_of_date = as_of_date

    def build(
        self,
        transactions: list[dict],
        business_age_months: int,
        bki_monthly_payments: Decimal,
    ) -> dict:
        """
        transactions: список dict с полями: booked_at (str 'YYYY-MM-DD'),
        direction ('IN'/'OUT'), amount_kopecks (int), category (str).
        """
        end_month = date(self.as_of_date.year, self.as_of_date.month, 1) - date.resolution
        start_month = date(end_month.year - 1, end_month.month, 1)

        monthly_data = defaultdict(
            lambda: {
                "revenue": Decimal("0"),
                "opex": Decimal("0"),
                "debt_svc": Decimal("0"),
            }
        )

        for tx in transactions:
            tx_date = date.fromisoformat(tx["booked_at"])
            if tx_date < start_month or tx_date > end_month:
                continue

            month_key = date(tx_date.year, tx_date.month, 1)
            amount = Decimal(tx["amount_kopecks"]) / Decimal("100")
            category = tx["category"]

            if category in REVENUE_CATS and tx["direction"] == "IN":
                monthly_data[month_key]["revenue"] += amount
            elif category in OPEX_CATS and tx["direction"] == "OUT":
                monthly_data[month_key]["opex"] += amount
            elif category in DEBT_SVC_CATS and tx["direction"] == "OUT":
                monthly_data[month_key]["debt_svc"] += amount

        sorted_months = sorted(monthly_data.keys())
        if len(sorted_months) < 6:
            return {"skipped": True, "reason": "ACCOUNT_HISTORY_INSUFFICIENT"}

        months = sorted_months[-12:]

        revenues = [monthly_data[m]["revenue"] for m in months]
        opexes = [monthly_data[m]["opex"] for m in months]
        debt_svcs = [monthly_data[m]["debt_svc"] for m in months]

        net_cashflows = [revenues[i] - opexes[i] for i in range(len(months))]
        last_6_net = net_cashflows[-6:]
        cfads = self._median(last_6_net)

        first_3_rev = sum(revenues[:3])
        last_3_rev = sum(revenues[-3:])
        if first_3_rev > 0:
            revenue_change_pct = ((last_3_rev / first_3_rev) - Decimal("1")) * Decimal("100")
        else:
            revenue_change_pct = Decimal("0")

        existing_debt_payments = sum(debt_svcs) / len(debt_svcs) if debt_svcs else Decimal("0")

        return {
            "h": len(months),
            "cfads": cfads,
            "revenue_change_pct": revenue_change_pct,
            "existing_debt_payments_rub": existing_debt_payments,
            "business_age_months": business_age_months,
            "monthly_data": {m.isoformat(): monthly_data[m] for m in months},
        }

    def _median(self, values: list[Decimal]) -> Decimal:
        if not values:
            return Decimal("0")
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        if n % 2 == 1:
            return sorted_vals[n // 2]
        else:
            return (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / Decimal("2")
