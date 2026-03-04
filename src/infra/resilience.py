"""Retry/backoff and circuit-breaker helpers."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


class CircuitBreakerOpenError(RuntimeError):
    """Raised when calls are blocked by an open circuit."""


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.4
    max_delay_seconds: float = 4.0
    jitter_ratio: float = 0.2

    def clamp_attempts(self) -> int:
        return max(1, int(self.max_attempts))

    def backoff_delay(self, attempt: int) -> float:
        attempt = max(1, attempt)
        base = min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
        jitter = base * self.jitter_ratio
        return float(max(0.0, base + random.uniform(-jitter, jitter)))


@dataclass
class _CircuitState:
    failures: int = 0
    opened_until_monotonic: float = 0.0


class CircuitBreakerRegistry:
    """Per-key circuit breaker state machine."""

    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 30.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._failure_threshold = max(1, int(failure_threshold))
        self._cooldown_seconds = max(1.0, float(cooldown_seconds))
        self._time_fn = time_fn or time.monotonic
        self._state: dict[str, _CircuitState] = {}
        self._lock = threading.Lock()

    def before_call(self, key: str) -> None:
        with self._lock:
            state = self._state.get(key)
            if state is None:
                return
            now = self._time_fn()
            if now < state.opened_until_monotonic:
                raise CircuitBreakerOpenError(
                    f"Circuit is open for '{key}' until {state.opened_until_monotonic:.2f}."
                )
            if state.opened_until_monotonic:
                # Half-open transition: allow call, keep accumulated failures only on new failure.
                state.opened_until_monotonic = 0.0
                state.failures = 0

    def record_success(self, key: str) -> None:
        with self._lock:
            self._state[key] = _CircuitState(failures=0, opened_until_monotonic=0.0)

    def record_failure(self, key: str) -> None:
        with self._lock:
            state = self._state.setdefault(key, _CircuitState())
            state.failures += 1
            if state.failures >= self._failure_threshold:
                state.opened_until_monotonic = self._time_fn() + self._cooldown_seconds
