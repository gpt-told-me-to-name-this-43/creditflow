"""Формат показа чисел в заключении — тот же, что у блока расчёта в UI.

Деньги — как `formatMoney` в web/src/lib/money.ts: группы по три цифры через неразрывный
пробел, копейки через запятую, `₽`, минус «−». DSCR и проценты — строка API без изменений
(«1.10», «-8.00 %»), срок — «36 мес.». Источник значений — `Scoring` карточки менеджера
(`app.manager.views.scoring_view`), поэтому подставленные числа побайтно совпадают с ним.
"""

from decimal import Decimal

NBSP = " "
MINUS = "−"


def format_money(value: str, *, kopecks: bool = True) -> str:
    amount = Decimal(value).quantize(Decimal("0.01"))
    sign = MINUS if amount < 0 else ""
    rubles, _, rest = f"{abs(amount):.2f}".partition(".")
    grouped = f"{int(rubles):,}".replace(",", NBSP)
    fraction = f",{rest}" if kopecks or rest != "00" else ""
    return f"{sign}{grouped}{fraction}{NBSP}₽"


def format_percent(value: str) -> str:
    return f"{value}{NBSP}%"


def format_months(value: int) -> str:
    return f"{value}{NBSP}мес."
