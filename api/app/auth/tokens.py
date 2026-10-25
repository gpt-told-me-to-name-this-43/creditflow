"""JWT HS256 (#5): `sub, role, iat, exp, jti`, TTL 8 ч, без refresh (ADR в docs/adr/).

Алгоритм фиксирован: `decode` принимает только HS256, поэтому токен с `alg=none` или
другим алгоритмом отклоняется. Все пять claims обязательны.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

ALGORITHM = "HS256"
TOKEN_TTL = timedelta(hours=8)
REQUIRED_CLAIMS = ("sub", "role", "iat", "exp", "jti")


class InvalidTokenError(Exception):
    """Подпись, алгоритм, срок или claims не прошли проверку. Причина в сообщении
    без самого токена."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    role: str
    jti: str


def issue_token(user_id: uuid.UUID, role: str, secret: str, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(issued.timestamp()),
        "exp": int((issued + TOKEN_TTL).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_token(token: str, secret: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            options={"require": list(REQUIRED_CLAIMS), "verify_iat": True},
        )
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as exc:
        raise InvalidTokenError(type(exc).__name__) from None
    role, jti = payload["role"], payload["jti"]
    if not isinstance(role, str) or not isinstance(jti, str) or not jti:
        raise InvalidTokenError("bad claims")
    return TokenClaims(user_id=user_id, role=role, jti=jti)
