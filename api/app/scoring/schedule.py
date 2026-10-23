"""Аннуитетный график платежей (design.md §3.4 «График платежей»). Используется в #7.

interest_i  = round_half_up(balance_{i−1} · r)
principal_i = P − interest_i,  P = round_half_up(S · A(r, n))
последний платёж корректируется так, чтобы остаток стал ровно 0,00
дата i-го платежа = дата выдачи + i мес.; для 29–31 числа — последний день короткого месяца
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.scoring.money import ZERO, exact, round_money, to_decimal
from app.scoring.risk import annuity_factor


@dataclass(frozen=True)
class ScheduleRow:
    number: int
    due_date: date
    payment_rub: Decimal
    interest_rub: Decimal
    principal_rub: Decimal
    balance_after_rub: Decimal


def add_months(d: date, months: int) -> date:
    """Всегда от исходной даты, а не от предыдущего платежа: 31.01 → 28/29.02 → 31.03."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


@exact
def build_schedule(
    amount_rub: Decimal, annual_rate_pct: Decimal, term_months: int, issued_on: date
) -> tuple[ScheduleRow, ...]:
    amount = to_decimal(amount_rub)
    r = to_decimal(annual_rate_pct) / 1200
    payment = round_money(amount * annuity_factor(annual_rate_pct, term_months))
    balance = amount
    rows = []
    for i in range(1, term_months + 1):
        interest = round_money(balance * r)
        if i == term_months:
            principal = balance  # добираем остаток: итог ровно 0,00
            current = principal + interest
        else:
            principal = payment - interest
            current = payment
        balance -= principal
        rows.append(ScheduleRow(i, add_months(issued_on, i), current, interest, principal, balance))
    assert balance == ZERO
    return tuple(rows)
