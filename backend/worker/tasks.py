"""Lease/fencing protects run ownership across retries, duplicates and cancellation."""

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import async_session_maker
from app.core.evidence import EMPTY_CORPUS_ADVISORY, EMPTY_CORPUS_REASON
from app.core.telemetry import RUN_LATENCY_HISTOGRAM
from app.models.compliance import CanonicalProvision, ComplianceRun, ExecutionAttempt, RunStatus
from llm.adapter import ModelUnavailable
from retrieval.hybrid_search import HybridSearchEngine
from sqlalchemy import func, select
from worker.agents.graph import build_compliance_graph, review
from worker.celery_app import celery_app
from worker.core.circuit_breaker import CircuitBreakerOpenException
from worker.tools.corpus_search import run_search_engine

logger = logging.getLogger(__name__)
_worker_loop = None


def run_async(coro):
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop.run_until_complete(coro)


@celery_app.task(name="worker.tasks.execute_compliance_run", bind=True, acks_late=True)
def execute_compliance_run(self, run_id_str, correlation_id=None):
    return run_async(_async_execute_run(self, run_id_str, correlation_id, time.monotonic()))


def can_claim(run, now):
    return run.status == RunStatus.QUEUED or (
        run.status == RunStatus.RUNNING
        and (run.lease_expires_at is None or run.lease_expires_at <= now)
    )


def owns_attempt(run, attempt_id):
    return (
        run is not None and run.status == RunStatus.RUNNING and run.active_attempt_id == attempt_id
    )


def reason_over_snapshot(state, provisions):
    if not provisions:
        result = review(EMPTY_CORPUS_REASON)
        result["final_advisory"] = EMPTY_CORPUS_ADVISORY
        result["execution_steps"] = [
            {"step_name": "evidence_preflight", "decision": "EMPTY_CORPUS"}
        ]
        return result
    engine = HybridSearchEngine()
    engine.load_corpus(provisions, index_vectors=False)
    token = run_search_engine.set(engine)
    try:
        return build_compliance_graph().invoke(state)
    finally:
        run_search_engine.reset(token)


async def _async_execute_run(task, run_id_str, correlation_id, start_time):
    run_uuid = uuid.UUID(run_id_str)
    now = datetime.now(timezone.utc)
    attempt_id = uuid.uuid4()
    async with async_session_maker() as db:
        run = (
            await db.execute(
                select(ComplianceRun).where(ComplianceRun.run_id == run_uuid).with_for_update()
            )
        ).scalar_one_or_none()
        if run is None or not can_claim(run, now):
            return {"status": "ignored"}
        number = (
            await db.execute(
                select(func.count(ExecutionAttempt.attempt_id)).where(
                    ExecutionAttempt.run_id == run_uuid
                )
            )
        ).scalar() + 1
        if run.active_attempt_id:
            old = await db.get(ExecutionAttempt, run.active_attempt_id)
            if old and old.status == "RUNNING":
                old.status, old.finished_at = "EXPIRED", now
        if number > settings.MAX_RUN_ATTEMPTS:
            run.status, run.completed_at = RunStatus.FAILED, now
            run.active_attempt_id, run.lease_expires_at = None, None
            run.route_reason = "Execution attempts exhausted after interrupted processing."
            await db.commit()
            return {"status": "FAILED"}
        run.status, run.active_attempt_id = RunStatus.RUNNING, attempt_id
        run.lease_expires_at = now + timedelta(seconds=settings.RUN_LEASE_SECONDS)
        db.add(
            ExecutionAttempt(
                attempt_id=attempt_id,
                run_id=run_uuid,
                worker_id=f"{socket.gethostname()}-{os.getpid()}",
                attempt_number=number,
                correlation_id=run.correlation_id,
                status="RUNNING",
            )
        )
        state = dict(
            run_id=str(run_uuid),
            client_id=run.client_id,
            query_text=run.query_text,
            scenario_date=run.scenario_date.isoformat(),
            employment_start_date=run.employment_start_date.isoformat()
            if run.employment_start_date
            else None,
            employment_end_date=run.employment_end_date.isoformat()
            if run.employment_end_date
            else None,
            establishment_size=run.establishment_size,
            establishment_category=run.establishment_category,
            domain_hint=run.domain_hint,
            correlation_id=run.correlation_id,
            research_pass=0,
            execution_steps=[],
            tool_history=[],
            retrieved_provisions={},
            business_route=None,
        )
        await db.commit()
    error = None
    try:
        async with asyncio.timeout(settings.RUN_TIMEOUT_SECONDS):
            async with async_session_maker() as db:
                provisions = (await db.execute(select(CanonicalProvision))).scalars().all()
                snapshot = [
                    {
                        column.name: getattr(p, column.name)
                        for column in CanonicalProvision.__table__.columns
                    }
                    for p in provisions
                ]
            result = await asyncio.to_thread(reason_over_snapshot, state, snapshot)
    except TimeoutError:
        result = review("The evidence review reached its processing time limit. Please retry.")
        result["execution_steps"] = [{"step_name": "processing", "decision": "TIMEOUT"}]
    except (ModelUnavailable, CircuitBreakerOpenException):
        result = review("Model service unavailable; automated advice was not generated.")
        result["execution_steps"] = [{"step_name": "model", "decision": "UNAVAILABLE"}]
    except Exception as exc:
        logger.error("Run %s processing failed (%s)", run_id_str, type(exc).__name__)
        error = "Processing failed. Please retry with a new inquiry or contact the operator."
        result = {
            "execution_steps": [
                {"step_name": "processing", "decision": "FAILED", "error_type": type(exc).__name__}
            ]
        }
    async with async_session_maker() as db:
        run = (
            await db.execute(
                select(ComplianceRun).where(ComplianceRun.run_id == run_uuid).with_for_update()
            )
        ).scalar_one_or_none()
        attempt = await db.get(ExecutionAttempt, attempt_id)
        now = datetime.now(timezone.utc)
        if not owns_attempt(run, attempt_id):
            if attempt and attempt.status == "RUNNING":
                attempt.status, attempt.finished_at = "SUPERSEDED", now
                await db.commit()
            return {"status": "superseded"}
        run.status = RunStatus.FAILED if error else RunStatus.COMPLETED
        run.completed_at, run.lease_expires_at, run.active_attempt_id = now, None, None
        run.route_reason = error or result.get("route_reason")
        if not error and settings.LLM_PROVIDER == "stub":
            run.route_reason = (
                "Test simulator result. Semantic legal verification was not performed. "
                + (run.route_reason or "")
            )
        run.business_route = result.get("business_route")
        run.advisory_text = result.get("final_advisory")
        run.citations = result.get("final_citations", [])
        run.extracted_entities = result.get("extracted_facts", {})
        run.claim_digest = result.get("claim_digest")
        run.prompt_version = f"v2-extractive:{settings.LLM_PROVIDER}"
        run.execution_trace = result.get("execution_steps", [])
        attempt.status, attempt.finished_at = run.status.value, now
        attempt.error_message = error
        attempt.step_metrics = {"steps": run.execution_trace}
        await db.commit()
        RUN_LATENCY_HISTOGRAM.labels(
            route=run.business_route.value if run.business_route else "NONE",
            status=run.status.value,
        ).observe(time.monotonic() - start_time)
        return {"run_id": run_id_str, "status": run.status.value}


@celery_app.task(name="worker.tasks.reconcile_outbox")
def reconcile_outbox():
    from app.core.outbox_reconcile import reconcile_pending_events

    return run_async(reconcile_pending_events())
