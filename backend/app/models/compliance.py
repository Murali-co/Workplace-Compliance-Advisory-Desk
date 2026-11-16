"""Compliance data models for PostgreSQL."""

import enum
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.models.base import Base, TimestampMixin
from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class RunStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BusinessRoute(str, enum.Enum):
    ANSWER_WITH_CITATIONS = "ANSWER_WITH_CITATIONS"
    REQUEST_MORE_INFORMATION = "REQUEST_MORE_INFORMATION"
    LEGAL_COUNSEL_REVIEW = "LEGAL_COUNSEL_REVIEW"


class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    FAILED = "FAILED"


class ComplianceRun(Base, TimestampMixin):
    """Compliance Run persistence model."""

    __tablename__ = "compliance_runs"
    __table_args__ = (UniqueConstraint("client_id", "idempotency_key", name="uq_run_client_key"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(256), index=True, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Input Facts
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    scenario_date: Mapped[date] = mapped_column(Date, nullable=False)
    employment_start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    employment_end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    establishment_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    domain_hint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    establishment_category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Lifecycle & Routing
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False), default=RunStatus.QUEUED, nullable=False
    )
    business_route: Mapped[Optional[BusinessRoute]] = mapped_column(
        Enum(BusinessRoute, native_enum=False), nullable=True
    )
    route_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Advisory Output
    advisory_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    citations: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    extracted_entities: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    claim_digest: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    execution_trace: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSONB, nullable=True)
    active_attempt_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Correlation and Timing
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    attempts: Mapped[List["ExecutionAttempt"]] = relationship(
        "ExecutionAttempt", back_populates="run", cascade="all, delete-orphan"
    )


class ExecutionAttempt(Base, TimestampMixin):
    """Execution attempt tracking for runs."""

    __tablename__ = "execution_attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("compliance_runs.run_id", ondelete="CASCADE"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    step_metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    run: Mapped["ComplianceRun"] = relationship("ComplianceRun", back_populates="attempts")


class QuarantineRecord(Base):
    """Quarantine store for malformed requests rejected at boundary."""

    __tablename__ = "quarantine_records"

    quarantine_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    endpoint: Mapped[str] = mapped_column(String(256), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    error_details: Mapped[List[Dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    payload_snippet: Mapped[str] = mapped_column(Text, nullable=False)  # Bounded to 4KB


class OutboxEvent(Base, TimestampMixin):
    """Transactional Outbox for reliable queue reconciliation."""

    __tablename__ = "outbox_events"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False), default=OutboxStatus.PENDING, nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CanonicalProvision(Base, TimestampMixin):
    """Canonical statutory provisions stored in PostgreSQL."""

    __tablename__ = "canonical_provisions"

    provision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    act: Mapped[str] = mapped_column(String(256), nullable=False)
    chapter: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    section: Mapped[str] = mapped_column(String(32), nullable=False)
    subsection: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    clause: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_provision: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    provision_text: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    legal_status: Mapped[str] = mapped_column(String(64), nullable=False)
    notification_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    page_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    related_provisions: Mapped[Optional[List[str]]] = mapped_column(JSONB, nullable=True)
    source_doc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class FeedbackRecord(Base, TimestampMixin):
    """User satisfaction feedback for completed compliance runs (Requirement L6)."""

    __tablename__ = "feedback_records"

    feedback_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("compliance_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    satisfactory: Mapped[bool] = mapped_column(nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
