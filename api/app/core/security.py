"""Схема Bearer для OpenAPI и определение IP клиента за доверенным прокси (#5).

Проверка токена — `app.auth.deps.current_user`; здесь только объявление схемы, чтобы
`security` операций в OpenAPI не зависел от реализации.
"""

from ipaddress import ip_address

from fastapi import Request
from fastapi.security import HTTPBearer

from app.core.config import Settings

bearer = HTTPBearer(
    scheme_name="BearerAuth",
    bearerFormat="JWT",
    description=(
        "JWT HS256 из POST /auth/login. В контракте #6 сервер проверяет только наличие "
        "Bearer-заголовка; подпись, срок и роль проверяются начиная с #5."
    ),
    auto_error=False,
)


def client_ip(request: Request) -> str:
    """IP клиента для лимитов. `X-Real-IP` выставляет nginx (`$remote_addr`, перезаписывая
    входящий); верим ему, только если соединение пришло от доверенного прокси."""
    peer = request.client.host if request.client else ""
    settings: Settings = request.app.state.settings
    try:
        peer_ip = ip_address(peer)
    except ValueError:
        return peer
    if any(peer_ip in net for net in settings.trusted_proxy_cidrs):
        forwarded = request.headers.get("x-real-ip", "").strip()
        try:
            return str(ip_address(forwarded))
        except ValueError:
            pass
    return peer
