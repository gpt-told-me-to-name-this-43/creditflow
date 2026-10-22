from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation


def to_decimal(value: str | int | Decimal) -> Decimal:
    if isinstance(value, float):
        raise TypeError("Float is strictly forbidden. Use str, int, or Decimal.")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Invalid decimal value: {value}") from None


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def display_dscr(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def floor_to_10k(value: Decimal) -> Decimal:
    return (value // Decimal("10000")) * Decimal("10000")
