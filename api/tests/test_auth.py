"""Вход, JWT и лимиты входа (#5)."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.auth import router as auth_router
from app.auth.tokens import issue_token
from app.core.config import DEMO_SECRET_KEY, Settings
from app.core.ratelimit import LOGIN_FAILURE_THRESHOLD, RateLimits
from app.core.security import client_ip
from app.main import create_app
from app.seed import DEMO_PASSWORD, DEMO_USERS
from tests.conftest import (
    CLIENT_LOGIN,
    MANAGER_LOGIN,
    TEST_SECRET_KEY,
    bearer,
    demo_user_id,
)

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def make_app(
    make_settings: Callable[..., Settings],
    db_reset: None,
    running: Callable[[Any], Any],
    clock: FakeClock,
) -> Callable[..., FastAPI]:
    def make(**overrides: Any) -> FastAPI:
        app: FastAPI = running(create_app(make_settings(**overrides)))
        app.state.rate_limits = RateLimits(clock=clock)
        return app

    return make


@pytest.fixture
def app(make_app: Callable[..., FastAPI]) -> FastAPI:
    return make_app()


def login(client: TestClient, login: str, password: str = DEMO_PASSWORD) -> Any:
    return client.post(LOGIN, json={"login": login, "password": password})


# --- Вход ------------------------------------------------------------------------------


@pytest.mark.parametrize("user", DEMO_USERS, ids=lambda u: u.email)
def test_demo_login_and_me(app: FastAPI, user: Any) -> None:
    client = TestClient(app)
    response = login(client, user.email)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 8 * 3600
    claims = jwt.decode(body["access_token"], TEST_SECRET_KEY, algorithms=["HS256"])
    assert set(claims) == {"sub", "role", "iat", "exp", "jti"}
    assert claims["exp"] - claims["iat"] == 8 * 3600
    assert claims["role"] == user.role

    me = client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json() == {
        "id": str(demo_user_id(user.email)),
        "role": user.role,
        "full_name": user.full_name,
        "company_id": None,
    }


def test_login_is_case_insensitive(app: FastAPI) -> None:
    assert login(TestClient(app), " Director.TechService@CreditFlow.demo ").status_code == 200


def test_me_without_token_is_401(app: FastAPI) -> None:
    response = TestClient(app).get(ME)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_wrong_login_and_wrong_password_are_indistinguishable(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified: list[str] = []
    real_verify = auth_router._verify

    def spy(password_hash: str, password: str) -> bool:
        verified.append(password_hash)
        return real_verify(password_hash, password)

    monkeypatch.setattr(auth_router, "_verify", spy)
    client = TestClient(app)
    wrong_password = login(client, CLIENT_LOGIN, "not-the-password")
    wrong_login = login(client, "nobody@creditflow.demo")
    assert wrong_password.status_code == wrong_login.status_code == 401
    assert wrong_password.json() == wrong_login.json()
    assert wrong_login.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_password.headers.keys() == wrong_login.headers.keys()
    # Для несуществующего логина хеш тоже проверяется (фиктивный): время не выдаёт учётку.
    assert len(verified) == 2
    assert verified[1] == auth_router._DUMMY_HASH


# --- JWT -------------------------------------------------------------------------------


def _token(**claims: Any) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(demo_user_id(CLIENT_LOGIN)),
        "role": "CLIENT",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    payload.update(claims)
    payload = {k: v for k, v in payload.items() if v is not None}
    return jwt.encode(payload, TEST_SECRET_KEY, algorithm="HS256")


def _past(hours: int) -> int:
    return int((datetime.now(UTC) - timedelta(hours=hours)).timestamp())


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(_token(), id="valid-control"),
        pytest.param(_token(exp=_past(1), iat=_past(9)), id="expired"),
        pytest.param(
            jwt.encode({"sub": "x"}, "another-secret-another-secret-0123", algorithm="HS256"),
            id="foreign-signature",
        ),
        pytest.param(_token().rsplit(".", 1)[0] + ".AAAA", id="tampered"),
        pytest.param(
            jwt.encode(
                jwt.decode(_token(), options={"verify_signature": False}), "", algorithm="none"
            ),
            id="alg-none",
        ),
        pytest.param(
            jwt.encode(
                jwt.decode(_token(), options={"verify_signature": False}),
                TEST_SECRET_KEY,
                algorithm="HS512",
            ),
            id="other-alg",
        ),
        pytest.param(_token(role=None), id="no-role"),
        pytest.param(_token(sub=None), id="no-sub"),
        pytest.param(_token(jti=None), id="no-jti"),
        pytest.param(_token(iat=None), id="no-iat"),
        pytest.param(_token(exp=None), id="no-exp"),
        pytest.param(
            _token(iat=int((datetime.now(UTC) + timedelta(hours=1)).timestamp())),
            id="iat-in-future",
        ),
        pytest.param(_token(sub="not-a-uuid"), id="sub-not-uuid"),
        pytest.param(_token(sub=str(uuid.uuid4())), id="unknown-user"),
        pytest.param(_token(role="MANAGER"), id="role-differs-from-db"),
        pytest.param("not.a.jwt", id="garbage"),
        pytest.param(_token(sub=12345), id="sub-not-string"),
        pytest.param(_token(role=["CLIENT"]), id="role-not-string"),
        pytest.param(_token(jti=12345), id="jti-not-string"),
        pytest.param(_token(jti=""), id="jti-empty"),
        pytest.param(_token(iat="now"), id="iat-not-number"),
    ],
)
def test_invalid_tokens_are_401(app: FastAPI, token: str, request: pytest.FixtureRequest) -> None:
    response = TestClient(app).get(ME, headers={"Authorization": f"Bearer {token}"})
    if request.node.callspec.id == "valid-control":
        assert response.status_code == 200
        return
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_role_comes_from_db_not_payload(app: FastAPI) -> None:
    # Подписанный токен клиента с ролью MANAGER: роль в БД — CLIENT, доступа нет.
    forged = issue_token(demo_user_id(CLIENT_LOGIN), "MANAGER", TEST_SECRET_KEY)
    response = TestClient(app).get(
        "/api/v1/manager/stats", headers={"Authorization": f"Bearer {forged}"}
    )
    assert response.status_code == 401


def test_deleted_user_token_is_401(app: FastAPI) -> None:
    import sqlalchemy as sa

    from tests.conftest import TEST_DATABASE_URL

    headers = bearer(MANAGER_LOGIN)
    assert TestClient(app).get(ME, headers=headers).status_code == 200
    engine = sa.create_engine(TEST_DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM users WHERE email = :e"), {"e": MANAGER_LOGIN})
    engine.dispose()
    assert TestClient(app).get(ME, headers=headers).status_code == 401


# --- Секрет и демо-режим ---------------------------------------------------------------


def test_short_secret_blocks_start(make_settings: Callable[..., Settings]) -> None:
    secret = "too-short-secret"
    with pytest.raises(ValueError, match="APP_SECRET_KEY короче 32 байт") as exc:
        make_settings(app_secret_key=secret)
    assert secret not in str(exc.value)  # значение ключа не попадает в лог старта


def test_secret_is_measured_in_bytes(make_settings: Callable[..., Settings]) -> None:
    make_settings(app_secret_key="ключ" * 4)  # 16 символов, 32 байта UTF-8


@pytest.mark.parametrize(
    ("env", "demo_auth", "allowed"),
    [
        ("local", True, True),
        ("test", True, True),
        ("local", False, False),
        ("test", False, False),
        ("production", True, False),
        ("production", False, False),
    ],
)
def test_demo_secret_policy(
    make_settings: Callable[..., Settings], env: str, demo_auth: bool, allowed: bool
) -> None:
    def build() -> Settings:
        return make_settings(
            app_env=env, demo_auth_enabled=demo_auth, app_secret_key=DEMO_SECRET_KEY
        )

    if allowed:
        build()
    else:
        with pytest.raises(ValueError) as exc:
            build()
        assert DEMO_SECRET_KEY not in str(exc.value)


def test_production_demo_auth_requires_own_secret(make_settings: Callable[..., Settings]) -> None:
    """DEMO_AUTH_ENABLED в production разрешён (облачный демо-стенд показывает учётки),
    но только с собственным секретом: публичный демо-ключ дал бы подделать любой JWT."""
    settings = make_settings(app_env="production", demo_auth_enabled=True)
    assert settings.app_secret_key == TEST_SECRET_KEY
    with pytest.raises(ValueError):
        make_settings(app_env="production", demo_auth_enabled=True, app_secret_key=DEMO_SECRET_KEY)


def test_secret_not_in_settings_repr(make_settings: Callable[..., Settings]) -> None:
    assert TEST_SECRET_KEY not in repr(make_settings())


def test_demo_accounts_from_seed(make_app: Callable[..., FastAPI]) -> None:
    client = TestClient(make_app(demo_auth_enabled=True))
    accounts = client.get("/api/v1/auth/demo-accounts").json()
    assert [a["login"] for a in accounts] == [u.email for u in DEMO_USERS]
    by_login = {a["login"]: a for a in accounts}
    # scenario — полный текст из app/demo/accounts.py (#7), тот же, что в docs/demo-data.md
    assert "APPLICANT_NOT_AUTHORIZED" in by_login["accountant.bakery@creditflow.demo"]["scenario"]
    assert by_login[MANAGER_LOGIN]["role"] == "MANAGER"


# --- Лимиты входа ----------------------------------------------------------------------


def test_eleventh_login_per_minute_from_ip_is_429(app: FastAPI, clock: FakeClock) -> None:
    client = TestClient(app)
    for _ in range(10):
        assert login(client, CLIENT_LOGIN).status_code == 200
    response = login(client, CLIENT_LOGIN)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert response.json()["error"]["details"] == {"scope": "LOGIN", "retry_after_seconds": 60}
    assert response.headers["Retry-After"] == "60"
    clock.now += 60
    assert login(client, CLIENT_LOGIN).status_code == 200


def test_load_test_flag_disables_only_ip_limit(
    make_app: Callable[..., FastAPI], clock: FakeClock
) -> None:
    client = TestClient(make_app(load_test_enabled=True))
    for _ in range(30):
        assert login(client, CLIENT_LOGIN).status_code == 200
    for _ in range(5):
        assert login(client, MANAGER_LOGIN, "wrong").status_code == 401
    assert login(client, MANAGER_LOGIN).status_code == 429


def test_five_failures_lock_login_for_15_minutes(app: FastAPI, clock: FakeClock) -> None:
    client = TestClient(app)
    for _ in range(5):
        assert login(client, CLIENT_LOGIN, "wrong").status_code == 401
    locked = login(client, CLIENT_LOGIN)  # даже верный пароль
    assert locked.status_code == 429
    assert locked.json()["error"]["details"] == {"scope": "LOGIN", "retry_after_seconds": 900}
    assert locked.headers["Retry-After"] == "900"
    assert login(client, MANAGER_LOGIN).status_code == 200  # другие логины не затронуты
    clock.now += 15 * 60
    assert login(client, CLIENT_LOGIN).status_code == 200


def test_failures_counted_per_login_case_insensitively(app: FastAPI) -> None:
    client = TestClient(app)
    for variant in ("A@x.demo", "a@x.demo", " a@X.demo", "A@X.DEMO", "a@x.demo"):
        assert login(client, variant, "wrong").status_code == 401
    assert login(client, "a@x.demo", "wrong").status_code == 429  # несуществующий тоже


def test_success_resets_failures(app: FastAPI, clock: FakeClock) -> None:
    client = TestClient(app)
    for _ in range(4):
        login(client, CLIENT_LOGIN, "wrong")
    assert login(client, CLIENT_LOGIN).status_code == 200
    for _ in range(4):
        assert login(client, CLIENT_LOGIN, "wrong").status_code == 401
    clock.now += 60  # IP-окно: 10 запросов уже было
    assert login(client, CLIENT_LOGIN).status_code == 200


def test_failures_expire_after_15_minutes_without_attempts(app: FastAPI, clock: FakeClock) -> None:
    client = TestClient(app)
    for _ in range(4):
        login(client, CLIENT_LOGIN, "wrong")
    clock.now += 15 * 60
    assert login(client, CLIENT_LOGIN, "wrong").status_code == 401  # счёт начат заново
    assert login(client, CLIENT_LOGIN).status_code == 200


# --- IP клиента ------------------------------------------------------------------------


def _request(peer: str, real_ip: str | None, settings: Settings) -> Request:
    app = FastAPI()
    app.state.settings = settings
    headers = [(b"x-real-ip", real_ip.encode())] if real_ip is not None else []
    return Request(
        {"type": "http", "app": app, "client": (peer, 1234), "headers": headers, "path": "/"}
    )


@pytest.mark.parametrize(
    ("peer", "real_ip", "expected"),
    [
        ("172.18.0.5", "203.0.113.7", "203.0.113.7"),  # nginx в сети compose
        ("203.0.113.9", "198.51.100.1", "203.0.113.9"),  # прямой клиент подделывает заголовок
        ("172.18.0.5", "not-an-ip", "172.18.0.5"),
        ("172.18.0.5", None, "172.18.0.5"),
        ("testclient", "198.51.100.1", "testclient"),
    ],
)
def test_client_ip_trusts_only_proxies(
    make_settings: Callable[..., Settings], peer: str, real_ip: str | None, expected: str
) -> None:
    assert client_ip(_request(peer, real_ip, make_settings())) == expected


async def test_concurrent_failures_cannot_exceed_threshold(
    make_settings: Callable[..., Settings],
    db_reset: None,
    serve: Callable[[Any], Awaitable[httpx.AsyncClient]],
) -> None:
    """Попытки одного логина с разных IP одновременно: проверка блокировки не должна
    пропускать больше LOGIN_FAILURE_THRESHOLD паролей до записи неудач."""
    api = await serve(create_app(make_settings()))

    async def attempt(i: int) -> int:
        response = await api.post(
            LOGIN,
            json={"login": CLIENT_LOGIN, "password": f"wrong-{i}"},
            headers={"X-Real-IP": f"198.51.100.{i}"},
        )
        return response.status_code

    statuses = await asyncio.gather(*(attempt(i) for i in range(30)))
    assert statuses.count(401) == LOGIN_FAILURE_THRESHOLD
    assert statuses.count(429) == 30 - LOGIN_FAILURE_THRESHOLD
    locked = await api.post(LOGIN, json={"login": CLIENT_LOGIN, "password": DEMO_PASSWORD})
    assert locked.status_code == 429
