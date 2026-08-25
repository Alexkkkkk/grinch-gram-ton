"""Circuit breaker pattern for external API calls."""

import logging
import threading
import time
from enum import Enum
from functools import wraps
from typing import Callable, Optional

logger = logging.getLogger("circuit_breaker")


class State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self._state = State.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        with self._lock:
            if self._state == State.OPEN:
                if (
                    time.time() - (self._last_failure_time or 0)
                    >= self.recovery_timeout
                ):
                    self._state = State.HALF_OPEN
                    self._success_count = 0
                    logger.info("[%s] Transition to HALF_OPEN", self.name)
            return self._state

    def record_success(self):
        with self._lock:
            self._failure_count = 0
            if self._state == State.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = State.CLOSED
                    logger.info("[%s] Transition to CLOSED", self.name)

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._state == State.HALF_OPEN:
                self._state = State.OPEN
                logger.warning("[%s] HALF_OPEN failed — back to OPEN", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = State.OPEN
                logger.error(
                    "[%s] Transition to OPEN after %d failures",
                    self.name,
                    self._failure_count,
                )

    def call(self, fn: Callable, *args, **kwargs):
        state = self.state
        if state == State.OPEN:
            raise CircuitBreakerOpen(f"{self.name} circuit is OPEN")
        try:
            result = fn(*args, **kwargs)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure()
            raise

    def __call__(self, fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return self.call(fn, *args, **kwargs)

        return wrapper


class CircuitBreakerOpen(Exception):
    pass


dedust_breaker = CircuitBreaker("dedust", failure_threshold=3, recovery_timeout=30)
toncenter_breaker = CircuitBreaker(
    "toncenter", failure_threshold=5, recovery_timeout=60
)
