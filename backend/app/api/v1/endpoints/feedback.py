"""User Feedback Endpoint for Compliance Runs (Requirement L6)."""

from app.core.database import get_db
from app.core.security import get_client_id
from app.models.compliance import ComplianceRun, FeedbackRecord, RunStatus
from app.schemas.compliance import (
    FeedbackCreateRequest,
    FeedbackResponse,
    FeedbackSummaryResponse,
)
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit user feedback on a completed compliance advisory",
)
async def submit_feedback(
    payload: FeedbackCreateRequest,
    x_client_id: str = Depends(get_client_id),
    db: AsyncSession = Depends(get_db),
):
    # 1. Validate that the run exists and has reached a terminal state
    stmt = select(ComplianceRun).where(
        ComplianceRun.run_id == payload.run_id, ComplianceRun.client_id == x_client_id
    )
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Compliance run '{payload.run_id}' not found.",
        )

    if run.status not in [RunStatus.COMPLETED, RunStatus.FAILED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot submit feedback for run in non-terminal state '{run.status.value}'.",
        )

    # 3. Persist feedback
    record = FeedbackRecord(
        run_id=payload.run_id,
        client_id=x_client_id,
        satisfactory=payload.satisfactory,
        reason=payload.reason[:1000] if payload.reason else None,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return FeedbackResponse(
        feedback_id=record.feedback_id,
        run_id=record.run_id,
        satisfactory=record.satisfactory,
        reason=record.reason,
        created_at=record.created_at,
    )


@router.get(
    "/feedback/summary",
    response_model=FeedbackSummaryResponse,
    summary="Retrieve aggregated satisfaction feedback metrics",
)
async def get_feedback_summary(
    client_id: str = Depends(get_client_id), db: AsyncSession = Depends(get_db)
):
    total_res = await db.execute(
        select(func.count(FeedbackRecord.feedback_id)).where(FeedbackRecord.client_id == client_id)
    )
    total = total_res.scalar() or 0

    sat_res = await db.execute(
        select(func.count(FeedbackRecord.feedback_id)).where(
            FeedbackRecord.satisfactory.is_(True), FeedbackRecord.client_id == client_id
        )
    )
    sat_count = sat_res.scalar() or 0
    unsat_count = total - sat_count

    rate = (sat_count / total * 100.0) if total > 0 else 0.0

    return FeedbackSummaryResponse(
        total_feedback=total,
        satisfactory_count=sat_count,
        unsatisfactory_count=unsat_count,
        satisfaction_rate=round(rate, 2),
    )
