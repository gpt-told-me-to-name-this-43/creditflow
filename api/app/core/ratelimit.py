"""Ограничения частоты (#5, design.md §4). Счётчики в памяти процесса: api работает одним
процессом uvicorn; для нескольких реплик нужен Redis (path-to-production).

- `/auth/login`: не больше 10 запросов в минуту с одного IP (`LOGIN_PER_IP`); при
  `LOAD_TEST_ENABLED=true` этот лимит выключен.
- `/auth/login`: 5 неудачных попыток подряд на один логин (`LoginFailureLock`) закрывают
  вход по нему на 15 минут, даже с верным паролем. Счётчик сбрасывается успешным входом,
  окончанием блокировки или 15 минутами без неудачных попыток. Блокировка ставится и на
  несуществующий логин, чтобы ответ не выдавал, есть ли такая учётка.
- `POST …/sign/challenge`: `limit_challenge_issue` — не больше 5 выданных challenge на
  заявку за 15 минут. Запрос, завершившийся ошибкой, слот не занимает.

Превышение — `429 TOO_MANY_ATTEMPTS` с `details.scope`, `retry_after_seconds` и `Retry-After`.
"""

import math
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Hashable
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import Depends, Request

from app.auth.deps import CurrentUserDep
from app.core.errors import AppError
from app.schemas.common import ErrorCode, TooManyAttemptsDetails

Clock = Callable[[], float]

LOGIN_IP_LIMIT, LOGIN_IP_WINDOW = 10, 60.0
LOGIN_FAILURE_THRESHOLD, LOGIN_LOCK_SECONDS = 5, 15 * 60.0
CHALLENGE_LIMIT, CHALLENGE_WINDOW = 5, 15 * 60.0
# Защита памяти от перебора ключей: при переполнении сначала удаляются истёкшие записи.
MAX_KEYS = 100_000


def _ceil_seconds(seconds: float) -> int:
    return max(1, math.ceil(seconds))


class SlidingWindow:
    """Не больше `limit` событий за `window` секунд на ключ."""

    def __init__(self, limit: int, window: float, clock: Clock = time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[Hashable, deque[float]] = {}

    def _prune(self, hits: deque[float], now: float) -> None:
        while hits and hits[0] <= now - self.window:
            hits.popleft()

    def acquire(self, key: Hashable) -> int | None:
        """Занимает слот. Если лимит исчерпан — слот не занимается, возвращается
        Retry-After в секундах."""
        now = self._clock()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= MAX_KEYS:
                self._evict(now)
            hits = self._hits[key] = deque()
        self._prune(hits, now)
        if len(hits) >= self.limit:
            return _ceil_seconds(hits[0] + self.window - now)
        hits.append(now)
        return None

    def release(self, key: Hashable) -> None:
        """Возвращает последний занятый слот (операция не состоялась)."""
        hits = self._hits.get(key)
        if hits:
            hits.pop()

    def _evict(self, now: float) -> None:
        for key in list(self._hits):
            self._prune(self._hits[key], now)
            if not self._hits[key]:
                del self._hits[key]
        while len(self._hits) >= MAX_KEYS:
            del self._hits[next(iter(self._hits))]


@dataclass
class _Failures:
    count: int
    last_failure: float
    locked_until: float | None = None


class LoginFailureLock:
    def __init__(
        self,
        threshold: int = LOGIN_FAILURE_THRESHOLD,
        lock_seconds: float = LOGIN_LOCK_SECONDS,
        clock: Clock = time.monotonic,
    ) -> None:
        self.threshold, self.lock_seconds, self._clock = threshold, lock_seconds, clock
        self._state: dict[str, _Failures] = {}

    def _current(self, login: str, now: float) -> _Failures | None:
        state = self._state.get(login)
        if state is None:
            return None
        expired = (
            state.locked_until <= now
            if state.locked_until is not None
            else state.last_failure <= now - self.lock_seconds
        )
        if expired:
            del self._state[login]
            return None
        return state

    def retry_after(self, login: str) -> int | None:
        now = self._clock()
        state = self._current(login, now)
        if state is None or state.locked_until is None:
            return None
        return _ceil_seconds(state.locked_until - now)

    def failure(self, login: str) -> None:
        now = self._clock()
        state = self._current(login, now)
        if state is None:
            if len(self._state) >= MAX_KEYS:
                for key in list(self._state):
                    self._current(key, now)
            state = self._state[login] = _Failures(count=0, last_failure=now)
        state.count += 1
        state.last_failure = now
        if state.count >= self.threshold:
            state.locked_until = now + self.lock_seconds

    def success(self, login: str) -> None:
        self._state.pop(login, None)


@dataclass
class RateLimits:
    """Все счётчики приложения; живут в `app.state.rate_limits`."""

    clock: Clock = time.monotonic
    login_ip: SlidingWindow = field(init=False)
    login_failures: LoginFailureLock = field(init=False)
    challenge_issue: SlidingWindow = field(init=False)

    def __post_init__(self) -> None:
        self.login_ip = SlidingWindow(LOGIN_IP_LIMIT, LOGIN_IP_WINDOW, self.clock)
        self.login_failures = LoginFailureLock(clock=self.clock)
        self.challenge_issue = SlidingWindow(CHALLENGE_LIMIT, CHALLENGE_WINDOW, self.clock)


def too_many_attempts(scope: Literal["LOGIN", "CHALLENGE_ISSUE"], retry_after: int) -> AppError:
    return AppError(
        ErrorCode.TOO_MANY_ATTEMPTS,
        "Слишком много попыток, попробуйте позже",
        TooManyAttemptsDetails(scope=scope, retry_after_seconds=retry_after),
    )


def rate_limits(request: Request) -> RateLimits:
    limits: RateLimits = request.app.state.rate_limits
    return limits


async def _challenge_slot(
    application_id: uuid.UUID,
    user: CurrentUserDep,
    limits: Annotated[RateLimits, Depends(rate_limits)],
) -> AsyncIterator[None]:
    key = (user.id, application_id)
    retry_after = limits.challenge_issue.acquire(key)
    if retry_after is not None:
        raise too_many_attempts("CHALLENGE_ISSUE", retry_after)
    try:
        yield
    except Exception:
        limits.challenge_issue.release(key)
        raise


async def limit_challenge_issue(
    _: Annotated[None, Depends(_challenge_slot, scope="function")],
) -> None:
    """`dependencies=[Depends(limit_challenge_issue)]` на `POST …/sign/challenge`."""
