"""Finish inquiries without queueing when there is no canonical evidence to search."""

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.state_machine import validate_run_transition
from app.models.compliance import BusinessRoute, CanonicalProvision, ComplianceRun, RunStatus
from sqlalchemy import and_, or_, select, update

EMPTY_CORPUS_REASON = "No verified statutory evidence is available in the corpus."
EMPTY_CORPUS_ADVISORY = (
    "The operator must import verified statutory provisions before this inquiry can be "
    "checked. Submit a new inquiry after the evidence is available. For an immediate "
    "assessment, consult qualified legal counsel. No referral has been sent."
)


async def complete_if_corpus_empty(db, run):
    """Atomically finish only queued work; never overwrite a worker or cancellation.

    The caller commits the transaction. The NOT EXISTS check and queued-state
    condition are part of the same update, including for previously queued runs.
    """
    if run.status != RunStatus.QUEUED:
        return False
    completed = await db.execute(
        update(ComplianceRun)
        .where(
            ComplianceRun.run_id == run.run_id,
            ComplianceRun.client_id == run.client_id,
            ComplianceRun.status == RunStatus.QUEUED,
            ~select(CanonicalProvision.provision_id).exists(),
        )
        .values(
            status=RunStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
            business_route=BusinessRoute.LEGAL_COUNSEL_REVIEW,
            route_reason=EMPTY_CORPUS_REASON,
            advisory_text=EMPTY_CORPUS_ADVISORY,
            citations=[],
            active_attempt_id=None,
            lease_expires_at=None,
            prompt_version="evidence-preflight:v1",
            execution_trace=[{"step_name": "evidence_preflight", "decision": "EMPTY_CORPUS"}],
        )
        .returning(ComplianceRun.run_id)
        .execution_options(synchronize_session=False)
    )
    if completed.scalar_one_or_none() is None:
        return False
    validate_run_transition(RunStatus.QUEUED, RunStatus.COMPLETED)
    await db.refresh(run)
    return True


async def complete_if_overdue(db, run):
    """Fence delayed or abandoned work so the UI always reaches an outcome."""
    if run.status not in (RunStatus.QUEUED, RunStatus.RUNNING):
        return False
    now = datetime.now(timezone.utc)
    queue_cutoff = now - timedelta(seconds=settings.QUEUE_WAIT_TIMEOUT_SECONDS)
    deadline = now - timedelta(seconds=settings.RESPONSE_DEADLINE_SECONDS)
    if run.created_at > deadline and (
        run.status != RunStatus.QUEUED or run.created_at > queue_cutoff
    ):
        return False
    updated = await db.execute(
        update(ComplianceRun)
        .where(
            ComplianceRun.run_id == run.run_id,
            ComplianceRun.client_id == run.client_id,
            ComplianceRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
            or_(
                ComplianceRun.created_at <= deadline,
                and_(
                    ComplianceRun.status == RunStatus.QUEUED,
                    ComplianceRun.created_at <= queue_cutoff,
                ),
            ),
        )
        .values(
            status=RunStatus.FAILED,
            completed_at=now,
            active_attempt_id=None,
            lease_expires_at=None,
            route_reason="The inquiry could not finish within the response time limit.",
            advisory_text=(
                "Please submit the inquiry again. If this repeats, ask the operator to check "
                "the processing service and local model. No verified answer was generated."
            ),
            citations=[],
            execution_trace=[{"step_name": "response_deadline", "decision": "TIMEOUT"}],
        )
        .returning(ComplianceRun.run_id)
        .execution_options(synchronize_session=False)
    )
    if updated.scalar_one_or_none() is None:
        return False
    await db.refresh(run)
    return True
