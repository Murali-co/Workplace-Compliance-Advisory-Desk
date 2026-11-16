"""Unit tests for run lifecycle state transitions."""

import pytest
from app.core.state_machine import InvalidStateTransitionError, validate_run_transition
from app.models.compliance import RunStatus


def test_permitted_transitions():
    """Tests all declared legal lifecycle transitions."""
    # QUEUED -> RUNNING
    validate_run_transition(RunStatus.QUEUED, RunStatus.RUNNING)

    # Evidence preflight can finish without worker execution.
    validate_run_transition(RunStatus.QUEUED, RunStatus.COMPLETED)

    # RUNNING -> COMPLETED
    validate_run_transition(RunStatus.RUNNING, RunStatus.COMPLETED)

    # RUNNING -> FAILED
    validate_run_transition(RunStatus.RUNNING, RunStatus.FAILED)

    # QUEUED -> CANCELLED
    validate_run_transition(RunStatus.QUEUED, RunStatus.CANCELLED)

    # RUNNING -> CANCELLED
    validate_run_transition(RunStatus.RUNNING, RunStatus.CANCELLED)

    # Idempotent self-transition
    validate_run_transition(RunStatus.QUEUED, RunStatus.QUEUED)
    validate_run_transition(RunStatus.RUNNING, RunStatus.RUNNING)
    validate_run_transition(RunStatus.COMPLETED, RunStatus.COMPLETED)


def test_rejected_illegal_transitions():
    """Tests that unauthorized transitions raise InvalidStateTransitionError."""
    # COMPLETED cannot revert to RUNNING
    with pytest.raises(InvalidStateTransitionError):
        validate_run_transition(RunStatus.COMPLETED, RunStatus.RUNNING)

    # COMPLETED cannot be CANCELLED
    with pytest.raises(InvalidStateTransitionError):
        validate_run_transition(RunStatus.COMPLETED, RunStatus.CANCELLED)

    # FAILED cannot transition to COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        validate_run_transition(RunStatus.FAILED, RunStatus.COMPLETED)

    # QUEUED cannot fail without an execution attempt.
    with pytest.raises(InvalidStateTransitionError):
        validate_run_transition(RunStatus.QUEUED, RunStatus.FAILED)
