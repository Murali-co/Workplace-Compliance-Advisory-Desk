"""Recover undelivered queued work and expired leases, with locked outbox rows."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.database import async_session_maker
from app.core.outbox import dispatch_celery_task
from app.models.compliance import ComplianceRun, OutboxEvent, OutboxStatus, RunStatus
from sqlalchemy import and_, or_, select

logger = logging.getLogger(__name__)


async def reconcile_pending_events(max_age_seconds=30):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=max_age_seconds)
    count = 0
    async with async_session_maker() as db:
        rows = (
            await db.execute(
                select(OutboxEvent, ComplianceRun)
                .join(ComplianceRun, ComplianceRun.run_id == OutboxEvent.run_id)
                .where(
                    OutboxEvent.updated_at <= cutoff,
                    or_(
                        ComplianceRun.status == RunStatus.QUEUED,
                        and_(
                            ComplianceRun.status == RunStatus.RUNNING,
                            or_(
                                ComplianceRun.lease_expires_at <= now,
                                ComplianceRun.lease_expires_at.is_(None),
                            ),
                        ),
                    ),
                )
                .with_for_update(skip_locked=True)
                .limit(50)
            )
        ).all()
        for event, run in rows:
            event.retry_count += 1
            event.updated_at = now
            try:
                await asyncio.to_thread(dispatch_celery_task, str(run.run_id), run.correlation_id)
                event.status = OutboxStatus.DISPATCHED
                count += 1
            except Exception as exc:
                logger.warning("Outbox redispatch unavailable (%s)", type(exc).__name__)
        await db.commit()
    return count


if __name__ == "__main__":
    asyncio.run(reconcile_pending_events(0))
