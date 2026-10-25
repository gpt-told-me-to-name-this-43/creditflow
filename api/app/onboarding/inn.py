"""Контрольные цифры ИНН (алгоритм ФНС): 10 цифр — юрлицо, 12 — физлицо и ИП."""

_W10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_W11 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_W12 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _digit(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def is_valid_inn(inn: str) -> bool:
    if not inn.isascii() or not inn.isdigit():
        return False
    if len(inn) == 10:
        return _digit(inn, _W10) == int(inn[9])
    if len(inn) == 12:
        return _digit(inn, _W11) == int(inn[10]) and _digit(inn, _W12) == int(inn[11])
    return False
