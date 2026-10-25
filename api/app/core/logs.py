"""JSON-логи structlog (#5): `ts, level, event, request_id, user_id, role, …`.

Логи библиотек (stdlib `logging`, uvicorn) проходят через те же процессоры, поэтому
маскирование действует на все записи. Тела запросов не логируются вовсе;
`mask_sensitive` — защита на случай, если чувствительное поле всё же попало в событие.
"""

import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

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
            structlog.processors.format_exc_info,
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
