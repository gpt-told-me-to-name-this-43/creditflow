"""Лимит выдачи кода подписания и счётчики в памяти (#5)."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.ratelimit import LoginFailureLock, RateLimits, SlidingWindow
from app.main import create_app
from tests.conftest import CLIENT_LOGIN, bearer
from tests.test_auth import FakeClock


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(
    make_settings: Callable[..., Settings],
    db_reset: None,
    running: Callable[[Any], Any],
    clock: FakeClock,
) -> TestClient:
    app: FastAPI = running(create_app(make_settings(demo_auth_enabled=True)))
    app.state.rate_limits = RateLimits(clock=clock)
    return TestClient(app, headers=bearer(CLIENT_LOGIN))


def challenge(client: TestClient, application_id: uuid.UUID, body: Any = None) -> Any:
    return client.post(
        f"/api/v1/applications/{application_id}/sign/challenge",
        json={"revision": 3} if body is None else body,
    )


def test_sixth_challenge_in_15_minutes_is_429(client: TestClient, clock: FakeClock) -> None:
    app_id = uuid.uuid4()
    for _ in range(5):
        assert challenge(client, app_id).status_code == 200
        clock.now += 60
    response = challenge(client, app_id)
    assert response.status_code == 429
    assert response.json()["error"]["details"] == {
        "scope": "CHALLENGE_ISSUE",
        "retry_after_seconds": 600,  # первый выдан 5 минут назад, окно — 15 минут
    }
    assert response.headers["Retry-After"] == "600"
    assert challenge(client, uuid.uuid4()).status_code == 200  # другая заявка
    clock.now += 600
    assert challenge(client, app_id).status_code == 200


def test_failed_requests_do_not_use_up_challenges(client: TestClient) -> None:
    app_id = uuid.uuid4()
    for _ in range(6):
        assert challenge(client, app_id, {"revision": "x"}).status_code == 422
    for _ in range(5):
        assert challenge(client, app_id).status_code == 200
    assert challenge(client, app_id).status_code == 429


def test_sliding_window_unit() -> None:
    clock = FakeClock()
    window = SlidingWindow(2, 10, clock)
    assert window.acquire("k") is None
    assert window.acquire("k") is None
    assert window.acquire("k") == 10
    clock.now += 4
    assert window.acquire("k") == 6
    window.release("k")  # отказ слот не занимал: освобождается последний занятый
    assert window.acquire("k") is None
    clock.now += 6.5
    assert window.acquire("k") is None


def test_login_lock_counts_attempts_in_flight() -> None:
    clock = FakeClock()
    lock = LoginFailureLock(threshold=3, lock_seconds=60, clock=clock)
    assert [lock.acquire("u") for _ in range(4)] == [None, None, None, 1]
    lock.release("u")  # попытка оборвалась ошибкой: бронь снята, неудачи нет
    assert lock.acquire("u") is None
    for _ in range(3):
        lock.failure("u")
    assert lock.acquire("u") == 60  # три неудачи — вход закрыт
    clock.now += 60
    assert lock.acquire("u") is None
    lock.success("u")
    assert lock.acquire("u") is None
    assert lock._pending == {"u": 1}
