"""Transactional Outbox and Queue Reconciliation."""

import logging
from typing import Any, Dict

from app.models.compliance import OutboxEvent, OutboxStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from worker.celery_app import celery_app

logger = logging.getLogger(__name__)


async def create_outbox_event(
    db: AsyncSession,
    run_id,
    event_type: str,
    payload: Dict[str, Any],
) -> OutboxEvent:
    """Creates a pending outbox record in the same transaction as the run."""
    event = OutboxEvent(
        run_id=run_id,
        event_type=event_type,
        payload=payload,
        status=OutboxStatus.PENDING,
    )
    db.add(event)
    return event


def dispatch_celery_task(run_id: str, correlation_id: str) -> str:
    """Enqueues task to Celery queue via Redis."""
    task = celery_app.send_task(
        "worker.tasks.execute_compliance_run",
        args=[str(run_id)],
        kwargs={"correlation_id": correlation_id},
        queue="compliance_tasks",
    )
    return task.id


async def mark_outbox_dispatched(db: AsyncSession, event_id) -> None:
    """Marks an outbox event as dispatched."""
    result = await db.execute(select(OutboxEvent).where(OutboxEvent.event_id == event_id))
    event = result.scalar_one_or_none()
    if event:
        event.status = OutboxStatus.DISPATCHED
        await db.commit()
