"""Pydantic schemas and data contracts for Compliance API.

Enforces Requirements F1, F2, and D1:
- Strict schema, range, categorical, and cross-field date validation.
- Published data contracts for ingestion.
- Rejection of impossible fact combinations.
- Tolerates unknown establishment details without marking them malformed.
"""

import hashlib
import json
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from app.models.compliance import BusinessRoute, RunStatus
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComplianceQueryRequest(BaseModel):
    """External API data contract for compliance inquiries."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query_text: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="The workplace compliance question or scenario statement.",
    )
    scenario_date: date = Field(
        ..., description="The reference date governing the legal scenario (ISO 8601 YYYY-MM-DD)."
    )
    employment_start_date: Optional[date] = Field(
        default=None, description="Date when the employee commenced service (if applicable)."
    )
    employment_end_date: Optional[date] = Field(
        default=None, description="Date when employment ended or will end (if applicable)."
    )
    establishment_size: Optional[int] = Field(
        default=None,
        strict=True,
        ge=1,
        le=1000000,
        description="Total headcount of employees employed in the establishment.",
    )
    domain_hint: Optional[
        Literal[
            "gratuity", "maternity_benefit", "workplace_harassment", "general_compliance", "other"
        ]
    ] = Field(default=None, description="Optional domain classification hint provided by caller.")
    establishment_category: Optional[
        Literal[
            "commercial_establishment",
            "factory",
            "mine",
            "plantation",
            "educational_institution",
            "hospital",
            "unspecified",
        ]
    ] = Field(
        default="unspecified",
        description="Type of establishment under Indian statutory definitions.",
    )

    @model_validator(mode="after")
    def validate_cross_field_dates(self) -> "ComplianceQueryRequest":
        """Cross-field checks for logical consistency."""
        # Check start date vs end date
        if self.employment_start_date and self.employment_end_date:
            if self.employment_start_date > self.employment_end_date:
                raise ValueError(
                    f"employment_start_date ({self.employment_start_date}) cannot be after "
                    f"employment_end_date ({self.employment_end_date})"
                )

        # Check employment start date vs scenario date
        if self.employment_start_date and self.scenario_date:
            if self.employment_start_date > self.scenario_date:
                raise ValueError(
                    f"employment_start_date ({self.employment_start_date}) cannot be in the future "
                    f"relative to scenario_date ({self.scenario_date})"
                )

        return self

    def compute_payload_hash(self) -> str:
        """Computes deterministic SHA-256 hash of normalized input fields."""
        normalized = {
            "query_text": self.query_text.strip(),
            "scenario_date": self.scenario_date.isoformat(),
            "employment_start_date": (
                self.employment_start_date.isoformat() if self.employment_start_date else None
            ),
            "employment_end_date": (
                self.employment_end_date.isoformat() if self.employment_end_date else None
            ),
            "establishment_size": self.establishment_size,
            "domain_hint": self.domain_hint,
            "establishment_category": self.establishment_category,
        }
        serialized = json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ComplianceQueryResponse(BaseModel):
    """HTTP 202 Accepted response payload."""

    run_id: uuid.UUID = Field(..., description="Unique asynchronous run identifier.")
    status: RunStatus = Field(..., description="Current system execution lifecycle status.")
    poll_url: str = Field(..., description="Relative URI to poll for run status and results.")
    created_at: datetime = Field(..., description="Timestamp when inquiry was durably accepted.")


class CitationItem(BaseModel):
    """Detailed statutory citation resolving to corpus passage."""

    source_url: Optional[str] = None
    page_number: Optional[str] = None
    notification_ref: Optional[str] = None
    act: str = Field(..., description="Title of the governing Act or Code.")
    section: str = Field(..., description="Section number or clause identifier.")
    clause: Optional[str] = Field(default=None, description="Sub-clause or proviso designation.")
    provision_id: str = Field(..., description="Unique provision identifier in corpus index.")
    legal_status: str = Field(
        ..., description="In Force, Repealed, or Uncommenced as of scenario date."
    )
    quoted_text: str = Field(
        ..., description="Exact textual excerpt supporting the advisory claim."
    )


class RunDetailResponse(BaseModel):
    """Detailed result payload returned by GET /api/v1/runs/{run_id}."""

    run_id: uuid.UUID
    client_id: str
    status: RunStatus
    business_route: Optional[BusinessRoute] = None
    route_reason: Optional[str] = None
    advisory_text: Optional[str] = None
    citations: Optional[List[CitationItem]] = None
    extracted_entities: Optional[Dict[str, Any]] = None
    claim_digest: Optional[str] = None
    prompt_version: Optional[str] = None
    correlation_id: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: Literal["ok"]
    service: str
    timestamp: datetime


class ReadinessComponent(BaseModel):
    status: bool
    details: Optional[str] = None


class ReadinessResponse(BaseModel):
    """Readiness probe response separating infrastructure from corpus."""

    status: Literal["ready", "not_ready"]
    infrastructure_ready: bool
    corpus_ready: bool
    components: Dict[str, ReadinessComponent]
    timestamp: datetime


class FeedbackCreateRequest(BaseModel):
    """Data contract for user satisfaction feedback (Requirement L6)."""

    run_id: uuid.UUID = Field(..., description="Run identifier being rated.")
    satisfactory: bool = Field(
        ...,
        strict=True,
        description="Whether the generated advisory or escalation was satisfactory.",
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Bounded textual explanation for the feedback rating.",
    )


class FeedbackResponse(BaseModel):
    """Response payload acknowledging feedback persistence."""

    feedback_id: uuid.UUID
    run_id: uuid.UUID
    satisfactory: bool
    reason: Optional[str] = None
    created_at: datetime


class FeedbackSummaryResponse(BaseModel):
    """Aggregated feedback statistics."""

    total_feedback: int
    satisfactory_count: int
    unsatisfactory_count: int
    satisfaction_rate: float
