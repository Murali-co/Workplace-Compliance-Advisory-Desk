"""State machine transition enforcement for Compliance Runs.

Enforces strict lifecycle rules:
- QUEUED -> RUNNING
- QUEUED -> COMPLETED (empty-corpus preflight)
- RUNNING -> COMPLETED
- RUNNING -> FAILED
- QUEUED -> CANCELLED
- RUNNING -> CANCELLED
Any other transition is rejected.
"""

from typing import Set, Tuple

from app.core.telemetry import RUN_TRANSITIONS_TOTAL
from app.models.compliance import RunStatus


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal lifecycle transition is attempted."""

    def __init__(self, current_status: RunStatus, target_status: RunStatus):
        super().__init__(
            f"Illegal state transition attempted from {current_status.value} to {target_status.value}"
        )
        self.current_status = current_status
        self.target_status = target_status


# Set of allowed (from_state, to_state) tuples
PERMITTED_TRANSITIONS: Set[Tuple[RunStatus, RunStatus]] = {
    (RunStatus.QUEUED, RunStatus.COMPLETED),
    (RunStatus.QUEUED, RunStatus.RUNNING),
    (RunStatus.RUNNING, RunStatus.COMPLETED),
    (RunStatus.RUNNING, RunStatus.FAILED),
    (RunStatus.QUEUED, RunStatus.CANCELLED),
    (RunStatus.RUNNING, RunStatus.CANCELLED),
}


def validate_run_transition(current_status: RunStatus, target_status: RunStatus) -> None:
    """Validates whether transitioning to target_status is permitted.

    Raises:
        InvalidStateTransitionError: If the transition is not allowed.
    """
    if current_status == target_status:
        # Idempotent no-op
        return

    if (current_status, target_status) not in PERMITTED_TRANSITIONS:
        raise InvalidStateTransitionError(current_status, target_status)

    RUN_TRANSITIONS_TOTAL.labels(
        from_status=current_status.value,
        to_status=target_status.value,
    ).inc()
