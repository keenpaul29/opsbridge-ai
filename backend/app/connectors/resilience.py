"""Retry-with-backoff and circuit breaker primitives for the outbound connector."""

import random
import time
from collections.abc import Callable


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """Opens after `threshold` consecutive failures; half-opens after `reset_s`."""

    def __init__(
        self, threshold: int, reset_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.threshold = threshold
        self.reset_s = reset_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self.reset_s:
            return False  # half-open: allow a probe request
        return True

    def before_call(self) -> None:
        if self.is_open:
            raise CircuitOpenError("circuit breaker is open")

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = self._clock()


def backoff_delay(attempt: int, base_s: float, retry_after_s: float | None = None) -> float:
    """Exponential backoff with full jitter; honours a server-provided Retry-After as a floor."""
    exp = base_s * (2**attempt)
    delay = random.uniform(0, exp)
    if retry_after_s is not None:
        delay = max(delay, retry_after_s)
    return delay
