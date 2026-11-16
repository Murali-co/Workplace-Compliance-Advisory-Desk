"""Compliance Queries API Endpoint.

Implements POST /api/v1/queries with idempotency, validation, quarantine,
and asynchronous Celery task dispatch.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import get_db
from app.core.evidence import complete_if_corpus_empty
from app.core.outbox import create_outbox_event, dispatch_celery_task, mark_outbox_dispatched
from app.core.quarantine import record_quarantine_entry
from app.core.security import get_client_id
from app.core.telemetry import QUARANTINED_REQUESTS_TOTAL, RUNS_CREATED_TOTAL
from app.models.compliance import ComplianceRun, RunStatus
from app.schemas.compliance import ComplianceQueryRequest, ComplianceQueryResponse
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from worker.guardrails.input_guard import inspect_input_guardrail

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/queries",
    response_model=ComplianceQueryResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a workplace compliance inquiry",
    description="Validates inquiry facts against data contract, ensures client idempotency, and enqueues background reasoning.",
)
async def submit_compliance_query(
    request: Request,
    response: Response,
    x_client_id: str = Depends(get_client_id),
    db: AsyncSession = Depends(get_db),
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=256
    ),
):
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))

    # Read raw body for validation & quarantine capture
    try:
        raw_body_bytes = b""
        async for chunk in request.stream():
            raw_body_bytes += chunk
            if len(raw_body_bytes) > settings.MAX_REQUEST_BYTES:
                raise HTTPException(413, "Request body is too large.")
        raw_body_str = raw_body_bytes.decode("utf-8")
        payload_json = json.loads(raw_body_str)
    except HTTPException:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Invalid JSON payload
        error_detail = [
            {"loc": ["body"], "msg": "Malformed JSON payload", "type": "value_error.json"}
        ]
        await record_quarantine_entry(
            db=db,
            client_id=x_client_id,
            endpoint=request.url.path,
            correlation_id=correlation_id,
            error_details=error_detail,
            raw_payload=raw_body_str if "raw_body_str" in locals() else "",
        )
        QUARANTINED_REQUESTS_TOTAL.labels(endpoint="/api/v1/queries").inc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": error_detail, "quarantined": True},
        )

    # Validate against Pydantic schema
    try:
        validated_request = ComplianceQueryRequest.model_validate(payload_json)
    except ValidationError as val_err:
        error_details = [
            {"loc": list(err["loc"]), "msg": err["msg"], "type": err["type"]}
            for err in val_err.errors()
        ]
        await record_quarantine_entry(
            db=db,
            client_id=x_client_id,
            endpoint=request.url.path,
            correlation_id=correlation_id,
            error_details=error_details,
            raw_payload=raw_body_str,
        )
        QUARANTINED_REQUESTS_TOTAL.labels(endpoint="/api/v1/queries").inc()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"errors": error_details, "quarantined": True},
        )

    safe, _ = inspect_input_guardrail(validated_request.query_text)
    if not safe:
        errors = [
            {
                "loc": ["query_text"],
                "msg": "Input contains unsupported instructions.",
                "type": "policy_rejected",
            }
        ]
        await record_quarantine_entry(
            db, x_client_id, request.url.path, correlation_id, errors, raw_body_str
        )
        raise HTTPException(422, detail={"errors": errors, "quarantined": True})

    payload_hash = validated_request.compute_payload_hash()

    # Idempotency check scoped by client_id
    if idempotency_key:
        # The lock serializes equal keys across API processes until commit.
        lock_id = int.from_bytes(
            hashlib.sha256(f"{x_client_id}\0{idempotency_key}".encode()).digest()[:8],
            "big",
            signed=True,
        )
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
        stmt = select(ComplianceRun).where(
            ComplianceRun.client_id == x_client_id,
            ComplianceRun.idempotency_key == idempotency_key,
        )
        result = await db.execute(stmt)
        existing_run = result.scalar_one_or_none()

        if existing_run and existing_run.created_at < datetime.now(timezone.utc) - timedelta(
            hours=24
        ):
            existing_run.idempotency_key = None
            await db.flush()
            existing_run = None

        if existing_run:
            if existing_run.payload_hash == payload_hash:
                # Same key, identical content -> return existing run
                poll_url = f"/api/v1/runs/{existing_run.run_id}"
                response.headers["Location"] = poll_url
                if existing_run.status in [
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                ]:
                    response.status_code = status.HTTP_200_OK
                else:
                    response.status_code = status.HTTP_202_ACCEPTED
                return ComplianceQueryResponse(
                    run_id=existing_run.run_id,
                    status=existing_run.status,
                    poll_url=poll_url,
                    created_at=existing_run.created_at,
                )
            else:
                # Same key, differing content -> HTTP 409 Conflict
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Idempotency conflict: key '{idempotency_key}' was previously submitted "
                        f"by client '{x_client_id}' with different payload."
                    ),
                )

    await enforce_rate_limit(x_client_id)

    # Create new Run
    run_id = uuid.uuid4()
    poll_url = f"/api/v1/runs/{run_id}"

    new_run = ComplianceRun(
        run_id=run_id,
        client_id=x_client_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        query_text=validated_request.query_text,
        scenario_date=validated_request.scenario_date,
        employment_start_date=validated_request.employment_start_date,
        employment_end_date=validated_request.employment_end_date,
        establishment_size=validated_request.establishment_size,
        domain_hint=validated_request.domain_hint,
        establishment_category=validated_request.establishment_category,
        status=RunStatus.QUEUED,
        correlation_id=correlation_id,
    )
    db.add(new_run)

    # No worker/model can generate verified evidence from an empty corpus.
    await db.flush()
    if await complete_if_corpus_empty(db, new_run):
        await db.commit()
        RUNS_CREATED_TOTAL.labels(client_id="all").inc()
        response.status_code = status.HTTP_200_OK
        response.headers["Location"] = poll_url
        return ComplianceQueryResponse(
            run_id=run_id,
            status=new_run.status,
            poll_url=poll_url,
            created_at=new_run.created_at,
        )

    # Create Outbox Event
    outbox_event = await create_outbox_event(
        db=db,
        run_id=run_id,
        event_type="COMPLIANCE_RUN_REQUESTED",
        payload={
            "run_id": str(run_id),
            "client_id": x_client_id,
            "correlation_id": correlation_id,
        },
    )
    await db.commit()
    await db.refresh(new_run)

    # Dispatch to Celery Queue
    try:
        await asyncio.to_thread(
            dispatch_celery_task, run_id=str(run_id), correlation_id=correlation_id
        )
        await mark_outbox_dispatched(db=db, event_id=outbox_event.event_id)
    except Exception as dispatch_err:
        logger.error(
            "Immediate dispatch failed for run %s (%s); outbox will retry",
            run_id,
            type(dispatch_err).__name__,
        )

    RUNS_CREATED_TOTAL.labels(client_id="all").inc()

    response.headers["Location"] = poll_url
    return ComplianceQueryResponse(
        run_id=run_id,
        status=RunStatus.QUEUED,
        poll_url=poll_url,
        created_at=new_run.created_at,
    )


async def enforce_rate_limit(client_id: str):
    import redis.asyncio as redis

    limiter = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
    key = "compliance:rate:" + hashlib.sha256(client_id.encode()).hexdigest()
    try:
        count = await limiter.eval(
            "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
            1,
            key,
        )
    except Exception:
        raise HTTPException(503, "Queue service unavailable. Please retry later.") from None
    finally:
        await limiter.aclose()
    if count > settings.RATE_LIMIT_REQUESTS_PER_MINUTE:
        raise HTTPException(
            429, "Too many inquiries. Please wait a minute.", headers={"Retry-After": "60"}
        )
