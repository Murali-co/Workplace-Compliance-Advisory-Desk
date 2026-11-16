"""Compliance Runs Status & Detail Endpoint."""

import uuid
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.evidence import complete_if_corpus_empty, complete_if_overdue
from app.core.security import get_client_id
from app.core.state_machine import InvalidStateTransitionError, validate_run_transition
from app.models.compliance import ComplianceRun, RunStatus
from app.schemas.compliance import RunDetailResponse
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.get(
    "/runs/{run_id}",
    response_model=RunDetailResponse,
    summary="Poll status and retrieve compliance advisory result",
)
async def get_compliance_run(
    run_id: uuid.UUID,
    client_id: str = Depends(get_client_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(ComplianceRun).where(
        ComplianceRun.run_id == run_id, ComplianceRun.client_id == client_id
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Compliance run '{run_id}' not found.",
        )

    # Recover inquiries queued before the empty-corpus preflight was introduced.
    if await complete_if_corpus_empty(db, run) or await complete_if_overdue(db, run):
        await db.commit()

    return RunDetailResponse(
        run_id=run.run_id,
        client_id=run.client_id,
        status=run.status,
        business_route=run.business_route,
        route_reason=run.route_reason,
        advisory_text=run.advisory_text,
        citations=run.citations,
        extracted_entities=run.extracted_entities,
        claim_digest=run.claim_digest,
        prompt_version=run.prompt_version,
        correlation_id=run.correlation_id,
        created_at=run.created_at,
        completed_at=run.completed_at,
        execution_trace=run.execution_trace or [],
    )


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunDetailResponse,
    summary="Cancel an active or queued run",
)
async def cancel_compliance_run(
    run_id: uuid.UUID,
    client_id: str = Depends(get_client_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ComplianceRun)
        .where(ComplianceRun.run_id == run_id, ComplianceRun.client_id == client_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Compliance run '{run_id}' not found.",
        )

    # Validate lifecycle transition
    if run.status != RunStatus.CANCELLED:
        try:
            validate_run_transition(run.status, RunStatus.CANCELLED)
        except InvalidStateTransitionError:
            raise HTTPException(409, "Only queued or running inquiries can be cancelled.") from None

    run.completed_at = run.completed_at or datetime.now(timezone.utc)
    run.active_attempt_id = None
    run.lease_expires_at = None
    run.status = RunStatus.CANCELLED
    run.route_reason = "Run cancelled by client request."
    await db.commit()
    await db.refresh(run)

    return RunDetailResponse(
        run_id=run.run_id,
        client_id=run.client_id,
        status=run.status,
        business_route=run.business_route,
        route_reason=run.route_reason,
        advisory_text=run.advisory_text,
        citations=run.citations,
        extracted_entities=run.extracted_entities,
        claim_digest=run.claim_digest,
        prompt_version=run.prompt_version,
        correlation_id=run.correlation_id,
        created_at=run.created_at,
        completed_at=run.completed_at,
        execution_trace=run.execution_trace or [],
    )
