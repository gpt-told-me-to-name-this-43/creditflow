"""`RequestContextMiddleware` (#5): request id, access-лог и защитные заголовки `api`.

- Входящий `X-Request-ID` принимается, если подходит под `REQUEST_ID_PATTERN`, иначе
  генерируется новый. Значение кладётся в `request_id_var` и возвращается в ответе.
- Access-лог: `method, path` (без query), `status, duration_ms, user_id, role`.
  Тело запроса и заголовки не логируются.
- Заголовки: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store` (все ответы api — данные), если обработчик не задал свой.
- Необработанное исключение до начала ответа превращается в `500 INTERNAL_ERROR` здесь,
  чтобы и у такого ответа были request id и защитные заголовки.
"""

import time
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_response
from app.core.logs import get_logger
from app.core.request_context import REQUEST_ID_PATTERN, access_log_fields, request_id_var
from app.schemas.common import ErrorBody, ErrorCode

logger = get_logger("app.access")

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def resolve_request_id(incoming: str | None) -> str:
    if incoming and REQUEST_ID_PATTERN.fullmatch(incoming):
        return incoming
    return uuid.uuid4().hex


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = resolve_request_id(Headers(scope=scope).get("x-request-id"))
        fields: dict[str, object] = {}
        rid_token = request_id_var.set(request_id)
        fields_token = access_log_fields.set(fields)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        status = 500
        started = time.perf_counter()
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            if response_started:
                raise
            logger.exception("unhandled error")
            response = error_response(
                500, ErrorBody(code=ErrorCode.INTERNAL_ERROR, message="Внутренняя ошибка сервера")
            )
            await response(scope, receive, send_with_headers)
        finally:
            logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                user_id=fields.get("user_id"),
                role=fields.get("role"),
            )
            structlog.contextvars.clear_contextvars()
            access_log_fields.reset(fields_token)
            request_id_var.reset(rid_token)
