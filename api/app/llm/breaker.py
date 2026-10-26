"""Circuit breaker LLM-провайдера (design.md §3.6).

После `threshold` сбоев подряд — `cooldown` секунд вызовы не идут к провайдеру: сразу
шаблоны или правила, `/health.llm = degraded`. По истечении паузы пропускается один пробный
вызов (half-open): успех закрывает breaker, сбой открывает его снова на `cooldown`.
"""

import time
from collections.abc import Callable
from typing import Literal

BreakerState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    def __init__(
        self,
        threshold: int = 5,
        cooldown: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold, self.cooldown, self._clock = threshold, cooldown, clock
        self.failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False

    @property
    def state(self) -> BreakerState:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at < self.cooldown:
            return "open"
        return "half_open"

    @property
    def degraded(self) -> bool:
        return self.state != "closed"

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._probe_in_flight:
            self._probe_in_flight = True
            return True
        return False

    def record_success(self) -> None:
        self.failures = 0
        self._opened_at = None
        self._probe_in_flight = False

    def record_failure(self) -> None:
        self.failures += 1
        if self._probe_in_flight or self.failures >= self.threshold:
            self._opened_at = self._clock()
        self._probe_in_flight = False
