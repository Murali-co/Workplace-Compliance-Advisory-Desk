"""Observability, telemetry, structured logging, and Prometheus metrics."""

import logging
import re
import time
import uuid

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Prometheus Metrics
REQUESTS_TOTAL = Counter(
    "compliance_requests_total",
    "Total HTTP requests received by API",
    ["method", "endpoint", "status_code"],
)

RUNS_CREATED_TOTAL = Counter(
    "compliance_runs_created_total",
    "Total compliance runs created and queued",
    ["client_id"],
)

RUN_TRANSITIONS_TOTAL = Counter(
    "compliance_run_transitions_total",
    "Total run state machine transitions",
    ["from_status", "to_status"],
)

QUARANTINED_REQUESTS_TOTAL = Counter(
    "compliance_quarantined_requests_total",
    "Total requests quarantined at ingestion boundary",
    ["endpoint"],
)

RUN_LATENCY_HISTOGRAM = Histogram(
    "compliance_run_execution_latency_seconds",
    "End-to-end execution latency for compliance runs (submission to terminal result)",
    ["route", "status"],
    buckets=(1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 45.0, 60.0, 90.0, 120.0),
)

CORPUS_PROVISIONS_GAUGE = Gauge(
    "compliance_corpus_provisions_count",
    "Total number of canonical provisions loaded in active corpus",
    ["jurisdiction"],
)

CIRCUIT_BREAKER_STATE_GAUGE = Gauge(
    "model_circuit_breaker_state",
    "Current state of model provider circuit breaker (0=closed, 1=open, 2=half-open)",
)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Propagates X-Correlation-ID across HTTP boundary."""

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "")
        corr_id = (
            incoming if re.fullmatch(r"[A-Za-z0-9._-]{1,128}", incoming) else str(uuid.uuid4())
        )
        request.state.correlation_id = corr_id
        start_time = time.time()

        response = await call_next(request)

        duration = time.time() - start_time
        response.headers["X-Correlation-ID"] = corr_id
        response.headers["X-Response-Time-Seconds"] = f"{duration:.4f}"

        # Track Prometheus metrics
        route = request.scope.get("route")
        endpoint = getattr(route, "path", "unmatched")
        # Normalize run-id paths
        if "/api/v1/runs/" in endpoint:
            endpoint = "/api/v1/runs/{run_id}"

        REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        ).inc()

        return response


def setup_structured_logging(log_level: str = "INFO") -> None:
    """Configures structured JSON-like format for application logs."""
    format_str = (
        '{"time": "%(asctime)s", "level": "%(levelname)s", "name": "%(name)s", '
        '"message": "%(message)s"}'
    )
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=format_str,
    )
