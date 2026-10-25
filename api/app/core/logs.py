"""JSON-логи structlog (#5): `ts, level, event, request_id, user_id, role, …`.

Логи библиотек (stdlib `logging`, uvicorn) проходят через те же процессоры, поэтому
маскирование действует на все записи. Тела запросов не логируются вовсе;
`mask_sensitive` — защита на случай, если чувствительное поле всё же попало в событие.
"""

import logging
import sys
import traceback
from collections.abc import Mapping
from typing import Any

import psycopg
import structlog
from pydantic import ValidationError
from sqlalchemy.exc import StatementError
from structlog.typing import EventDict, ExcInfo, Processor, WrappedLogger

MASK = "***"

# Ключи из #5 и секреты конфигурации. Сравнение без учёта регистра, `-` равен `_`
# (заголовок `Authorization`, `X-Test-Reset-Token`).
SENSITIVE_KEYS = frozenset(
    {
        "password",
        "access_token",
        "authorization",
        "api_key",
        "purpose_text",
        "answer_text",
        "comment",
        "messages",
        "llm_api_key",
        "app_secret_key",
        "test_reset_token",
        "x_test_reset_token",
    }
)


def _sensitive(key: object) -> bool:
    return isinstance(key, str) and key.lower().replace("-", "_") in SENSITIVE_KEYS


def _mask(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: MASK if _sensitive(k) else _mask(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_mask(item) for item in value]
    return value


def mask_sensitive(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Рекурсивно заменяет значения чувствительных ключей, в том числе во вложенных
    словарях и списках."""
    return {k: MASK if _sensitive(k) else _mask(v) for k, v in event_dict.items()}


def _safe_message(exc: BaseException) -> str:
    """Текст исключения для лога. Ошибки БД и валидации повторяют входные значения
    (`[parameters: …]`, `invalid input syntax …: "<значение>"`, `input_value=…`): от них
    остаются только код и место ошибки."""
    if isinstance(exc, StatementError | psycopg.Error):
        orig = getattr(exc, "orig", exc)
        diag = getattr(orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        sqlstate = getattr(orig, "sqlstate", None)
        return f"SQLSTATE {sqlstate}" + (f", constraint {constraint}" if constraint else "")
    if isinstance(exc, ValidationError):
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['type']}" for e in errors)
    return str(exc)


_CAUSE = "\nThe above exception was the direct cause of the following exception:\n\n"
_CONTEXT = "\nDuring handling of the above exception, another exception occurred:\n\n"


def _format_exception(exc_info: ExcInfo) -> str:
    """Как `traceback.format_exception`, но с `_safe_message` вместо текста исключения."""
    chain: list[tuple[BaseException, str]] = []
    exc: BaseException | None = exc_info[1]
    link = ""
    while exc is not None and all(exc is not seen for seen, _ in chain):
        chain.append((exc, link))
        if exc.__cause__ is not None:
            exc, link = exc.__cause__, _CAUSE
        else:
            exc, link = (None if exc.__suppress_context__ else exc.__context__), _CONTEXT
    parts: list[str] = []
    for exc, link in reversed(chain):
        parts.append("Traceback (most recent call last):\n")
        parts.extend(traceback.format_tb(exc.__traceback__))
        name = f"{type(exc).__module__}.{type(exc).__qualname__}"
        parts.append(f"{name}: {_safe_message(exc)}\n")
        if link:
            parts.append(link)
    return "".join(parts).rstrip("\n")


def _drop_color_message(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    event_dict.pop("color_message", None)  # дубль сообщения uvicorn с ANSI-кодами
    return event_dict


_SHARED: list[Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
    _drop_color_message,
]


def configure_logging(level: int = logging.INFO) -> None:
    structlog.configure(
        processors=[
            *_SHARED,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            # Трассировка — строкой, без локальных переменных: в них могут быть секреты.
            structlog.processors.ExceptionRenderer(_format_exception),
            mask_sensitive,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    # logging.config.fileConfig (alembic env.py) отключает уже созданные логгеры.
    for name, existing in logging.root.manager.loggerDict.items():
        if isinstance(existing, logging.Logger) and (name == "app" or name.startswith("app.")):
            existing.disabled = False
    # Access-лог пишет RequestContextMiddleware: в строке uvicorn есть query, нет request_id.
    logging.getLogger("uvicorn.access").disabled = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.stdlib.get_logger(name)
    return logger
