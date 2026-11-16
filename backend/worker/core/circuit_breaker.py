"""Circuit breaker pattern for external model provider protection.

Adheres to Requirement A5:
- Timeouts, bounded retries, circuit breaker on provider, and graceful degradation.
"""

import time
from typing import Optional

from app.core.telemetry import CIRCUIT_BREAKER_STATE_GAUGE


class CircuitBreakerOpenException(Exception):
    """Raised when model provider calls are blocked due to an open circuit."""

    pass


class CircuitBreaker:
    """In-memory circuit breaker."""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 60.0,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.failure_count = 0
        self.state = self.CLOSED
        self.last_failure_time: Optional[float] = None
        CIRCUIT_BREAKER_STATE_GAUGE.set(self.CLOSED)

    def record_success(self) -> None:
        """Records successful model call and resets breaker state."""
        self.failure_count = 0
        self.state = self.CLOSED
        CIRCUIT_BREAKER_STATE_GAUGE.set(self.CLOSED)

    def record_failure(self) -> None:
        """Records provider failure and trips breaker if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            CIRCUIT_BREAKER_STATE_GAUGE.set(self.OPEN)

    def check_state(self) -> None:
        """Validates if circuit allows execution.

        Raises:
            CircuitBreakerOpenException: If the breaker is OPEN.
        """
        now = time.time()
        if self.state == self.OPEN:
            if self.last_failure_time and (
                now - self.last_failure_time >= self.recovery_timeout_seconds
            ):
                # Transition to HALF_OPEN to test recovery
                self.state = self.HALF_OPEN
                CIRCUIT_BREAKER_STATE_GAUGE.set(self.HALF_OPEN)
            else:
                raise CircuitBreakerOpenException(
                    "Model provider circuit breaker is OPEN due to repeated upstream failures. "
                    "Inquiries are gracefully degraded to human legal review."
                )
