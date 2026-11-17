"""Unit tests for Circuit Breaker and Provider Failover (Requirement A5, Item 8)."""

import pytest
from worker.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpenException


def test_circuit_breaker_lifecycle():
    """Item 8: The circuit breaker opening when provider unavailable, and degradation path."""
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout_seconds=0.5)

    # Initial state is CLOSED
    breaker.check_state()
    assert breaker.state == CircuitBreaker.CLOSED

    # Record 2 failures (under threshold)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.CLOSED

    # 3rd failure trips breaker to OPEN
    breaker.record_failure()
    assert breaker.state == CircuitBreaker.OPEN

    # Calls while OPEN must raise CircuitBreakerOpenException
    with pytest.raises(CircuitBreakerOpenException):
        breaker.check_state()

    # Recovery: record a success resets state to CLOSED
    breaker.record_success()
    assert breaker.state == CircuitBreaker.CLOSED
    breaker.check_state()  # Does not raise
