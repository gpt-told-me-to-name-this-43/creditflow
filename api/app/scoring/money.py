"""Денежная арифметика ядра (design.md §3.4 «Денежные правила»).

- Все вычисления — `Decimal` в контексте `prec=34`, а не в глобальном (по умолчанию 28):
  результат не зависит от того, что настроил вызывающий код.
- `float` на входе публичной функции → `TypeError` (issue #6).
- Пороги сравниваются по НЕокруглённым значениям; округление — только для хранения и показа.
"""

from collections.abc import Callable
from decimal import ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, Context, Decimal, localcontext
from functools import wraps

DECIMAL_CONTEXT = Context(prec=34)
ZERO = Decimal(0)
CENT = Decimal("0.01")


def exact[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Выполняет функцию в контексте prec=34 и запрещает float в аргументах."""

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        for value in (*args, *kwargs.values()):
            if isinstance(value, float):
                raise TypeError(f"{fn.__name__}: float запрещён, передайте Decimal/int/str")
        with localcontext(DECIMAL_CONTEXT):
            return fn(*args, **kwargs)

    return wrapper


def to_decimal(value: Decimal | int | str) -> Decimal:
    """Строгое приведение: float и bool отклоняются (bool — подкласс int)."""
    if isinstance(value, float | bool):
        raise TypeError(f"Ожидается Decimal | int | str, получено {type(value).__name__}")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError(f"Недопустимое число: {value!r}")
    return result


def round_money(value: Decimal) -> Decimal:
    """Платёж и прочие деньги для хранения/показа: до копеек, ROUND_HALF_UP."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def display_dscr(value: Decimal) -> Decimal:
    """DSCR для показа: 2 знака, ROUND_DOWN (1.2487… → 1.24, а не 1.25)."""
    return value.quantize(CENT, rounding=ROUND_DOWN)


def floor_to(value: Decimal, step: Decimal) -> Decimal:
    """Округление вниз до кратного `step` (лимит — до 10 000 ₽)."""
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def money_str(value: Decimal) -> str:
    """Формат API/контракта: строка с двумя знаками, `^-?\\d+\\.\\d{2}$`."""
    return f"{round_money(value):.2f}"
