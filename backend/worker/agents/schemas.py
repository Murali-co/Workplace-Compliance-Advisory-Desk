"""Structured State Schema for LangGraph multi-agent compliance reasoning."""

from typing import Any, Dict, List, Optional, TypedDict

from app.models.compliance import BusinessRoute
from pydantic import BaseModel, ConfigDict, Field


class EvidenceClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provision_id: str
    assertion: str


class ResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    claims: list[EvidenceClaimResponse] = Field(max_length=50)


class EvidenceSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    provision_ids: list[str] = Field(max_length=10)


class VerificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    reasons: list[str]
    targeted_query: str
    approved: bool


class AtomicClaim(TypedDict):
    """An individual atomic statutory claim."""

    claim_id: str
    assertion: str
    cited_act: str
    cited_section: str
    cited_clause: Optional[str]
    provision_id: str
    verified: bool
    verification_notes: Optional[str]


class ToolExecutionRecord(TypedDict):
    """Record of a tool invocation."""

    tool_name: str
    arguments: Dict[str, Any]
    output_summary: str
    timestamp: str


class AdvisoryState(TypedDict):
    """LangGraph shared state passed between agents."""

    # Input Request Facts
    run_id: str
    client_id: str
    query_text: str
    scenario_date: str
    employment_start_date: Optional[str]
    employment_end_date: Optional[str]
    establishment_size: Optional[int]
    establishment_category: Optional[str]
    domain_hint: Optional[str]
    correlation_id: str

    # Extracted Facts & Entities
    extracted_facts: Dict[str, Any]

    # Iteration & Bounding
    research_pass: int
    tool_history: List[ToolExecutionRecord]
    retrieved_provisions: Dict[str, Dict[str, Any]]  # provision_id -> data

    # Draft Claims & Text
    draft_claims: List[AtomicClaim]
    draft_advisory: Optional[str]

    # Verification Findings
    verification_verdict: Optional[str]  # "APPROVED", "REJECTED", "ESCALATE"
    verification_reasons: List[str]
    targeted_research_query: Optional[str]

    # Final Outcome & Integrity
    business_route: Optional[BusinessRoute]
    route_reason: Optional[str]
    final_advisory: Optional[str]
    final_citations: List[Dict[str, Any]]
    claim_digest: Optional[str]
    verified_digest: Optional[str]
    prompt_version: str
    execution_steps: List[Dict[str, Any]]
