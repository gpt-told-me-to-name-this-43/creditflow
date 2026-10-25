"""Контекст текущего запроса: request id и поля access-лога (#5).

`request_id_var` выставляет `RequestContextMiddleware`; `ExtSimClient` и LLM-клиент берут
из него `X-Request-ID` по умолчанию, поэтому один id проходит nginx → api → ext-sim.
"""

import re
from contextvars import ContextVar
from typing import Any

# Тот же формат, что принимает ext-sim (ext-sim/app/main.py) и nginx (web/nginx.conf).
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Изменяемый словарь на запрос: current_user дописывает user_id и role, middleware читает
# их после ответа. Словарь, а не отдельные ContextVar: изменения внутри обработчика
# видны middleware, даже если контекст был скопирован.
access_log_fields: ContextVar[dict[str, Any] | None] = ContextVar("access_log_fields", default=None)


def set_access_log_field(name: str, value: Any) -> None:
    fields = access_log_fields.get()
    if fields is not None:
        fields[name] = value
