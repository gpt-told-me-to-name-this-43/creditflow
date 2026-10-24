"""Канонический JSON и inputs_hash (design.md §4 «Детерминированность»).

inputs_hash = sha256(canonical_json({"inputs": …, "versions": …})). Одинаковые входы
и версии → одинаковый хеш; смена версии ядра/политики/правил меняет хеш даже на тех же данных.
"""

import dataclasses
import hashlib
import json
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any

from app.scoring.versions import ENGINE_VERSION, POLICY_VERSION, RULES_VERSION


def _normalize(value: Any) -> Any:
    """Рекурсивно приводит вход к JSON-типам.

    Обход делаем сами, а не через `json.dumps(default=…)`: float json сериализует без
    вызова default, и запрет float молча не сработал бы.
    """
    if isinstance(value, float):
        raise TypeError("float запрещён во входах расчёта")
    if isinstance(value, Enum):  # до проверки str: StrEnum — тоже str, а нужен .value
        return value.value
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, Decimal):
        # 100, 100.0 и 100.00 — одно число → один хеш
        return format(value.normalize(), "f")
    if isinstance(value, date):
        return value.isoformat()
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _normalize(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(_normalize(k)): _normalize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize(v) for v in value]
    raise TypeError(f"Не сериализуется: {type(value).__name__}")


def canonical_json(data: Any) -> str:
    normalized = _normalize(data)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def inputs_hash(inputs: Any) -> str:
    payload = {
        "inputs": inputs,
        "versions": {"engine": ENGINE_VERSION, "policy": POLICY_VERSION, "rules": RULES_VERSION},
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
