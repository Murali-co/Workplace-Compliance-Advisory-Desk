"""FastAPI application entrypoint for Workplace Compliance Advisory Desk."""

import logging
import socket
from contextlib import asynccontextmanager

from app.api.v1.endpoints import feedback, health, queries, runs
from app.core.config import settings
from app.core.database import get_engine
from app.core.security import get_client_id
from app.core.telemetry import CorrelationIdMiddleware, setup_structured_logging
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from sqlalchemy.exc import SQLAlchemyError

setup_structured_logging(settings.LOG_LEVEL)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup is read-only; database migrations are explicit."""
    logger.info("Initializing Workplace Compliance Advisory Desk API...")

    yield
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    logger.info("Shutting down API...")


app = FastAPI(
    title="Workplace Compliance Advisory Desk API",
    version="1.0.0",
    description=(
        "Asynchronous research system providing cited source passages "
        "on Indian labour and employment law compliance (Code on Social Security 2020, "
        "POSH Act 2013, Payment of Gratuity Act 1972)."
    ),
    lifespan=lifespan,
)

# Middleware
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Idempotency-Key",
        "X-Client-ID",
        "X-Correlation-ID",
    ],
    expose_headers=["X-Correlation-ID", "Location"],
)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Include Routers
app.include_router(health.router, tags=["Health & Readiness"])
app.include_router(queries.router, prefix="/api/v1", tags=["Compliance Queries"])
app.include_router(runs.router, prefix="/api/v1", tags=["Compliance Runs"])
app.include_router(feedback.router, prefix="/api/v1", tags=["User Feedback"])


@app.get("/api/v1/workspace", tags=["Workspace"])
async def current_workspace(client_id: str = Depends(get_client_id)):
    """Check workspace identity without requiring a database connection."""
    return {"client_id": client_id}


@app.get("/", summary="Root index")
async def root():
    return {
        "service": "Workplace Compliance Advisory Desk",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_url": "/health",
        "ready_url": "/ready",
        "metrics_url": "/metrics",
    }


@app.exception_handler(SQLAlchemyError)
async def database_failure(request: Request, exc: SQLAlchemyError):
    logger.error("Database request failed: %s", type(exc).__name__)
    return JSONResponse(
        status_code=503, content={"detail": "Data service unavailable. Please retry later."}
    )


@app.exception_handler(ConnectionError)
@app.exception_handler(TimeoutError)
@app.exception_handler(socket.gaierror)
async def connection_failure(request: Request, exc: Exception):
    logger.warning("Data service connection unavailable (%s)", type(exc).__name__)
    return JSONResponse(
        status_code=503, content={"detail": "Data service unavailable. Please retry later."}
    )
