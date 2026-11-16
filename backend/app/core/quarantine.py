"""Quarantine management for rejected requests."""

import json
import logging
from typing import Any, Dict, List

from app.models.compliance import QuarantineRecord
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def record_quarantine_entry(
    db: AsyncSession,
    client_id: str,
    endpoint: str,
    correlation_id: str,
    error_details: List[Dict[str, Any]],
    raw_payload: str,
) -> QuarantineRecord:
    """Persists a malformed or policy-rejected request into quarantine.

    Enforces bounds on payload size to prevent denial-of-service / storage exhaustion.
    Never logs secrets or unbounded bodies.
    """
    import hashlib

    bounded_payload = json.dumps(
        {
            "sha256": hashlib.sha256(raw_payload.encode()).hexdigest(),
            "bytes": len(raw_payload.encode()),
            "content": "[REDACTED]",
        }
    )

    record = QuarantineRecord(
        client_id=client_id,
        endpoint=endpoint,
        correlation_id=correlation_id,
        error_details=error_details,
        payload_snippet=bounded_payload,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    logger.warning(
        "Request quarantined: quarantine_id=%s client_id=%s endpoint=%s errors=%d correlation_id=%s",
        record.quarantine_id,
        client_id,
        endpoint,
        len(error_details),
        correlation_id,
    )
    return record
