from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation, localcontext

MONEY_CONTEXT = localcontext(prec=34)

def to_decimal(value: str | int | Decimal) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Float is strictly forbidden. Use str, int, or Decimal.")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Invalid decimal value: {value}")

def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def display_dscr(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

def floor_to_10k(value: Decimal) -> Decimal:
    return (value // Decimal("10000")) * Decimal("10000")