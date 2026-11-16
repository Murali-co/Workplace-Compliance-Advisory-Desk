"""Data models for statutory hierarchy and provision ingestion."""

import datetime
import hashlib
from typing import List, Optional

from pydantic import BaseModel, Field


class ParsedProvision(BaseModel):
    """Structured representation of a parsed statutory provision."""

    provision_id: str = Field(..., description="Unique immutable provision identifier.")
    act: str = Field(..., description="Full title of the governing statute.")
    chapter: Optional[str] = Field(default=None, description="Chapter title or number.")
    section: str = Field(..., description="Section number (e.g. '53').")
    subsection: Optional[str] = Field(default=None, description="Subsection number (e.g. '1').")
    clause: Optional[str] = Field(
        default=None, description="Clause or proviso designation (e.g. 'Second Proviso')."
    )
    provision_type: str = Field(
        ...,
        description="Main Rule, Proviso (Statutory Exception), Statutory Definition, Penalty Provision, or Repeal and Savings.",
    )
    parent_provision: Optional[str] = Field(
        default=None, description="Parent section or subsection coordinate."
    )
    related_provisions: List[str] = Field(
        default_factory=list, description="Explicit cross-references cited within the provision."
    )
    provision_text: str = Field(..., description="Verbatim statutory text.")
    effective_from: Optional[datetime.date] = Field(
        default=None, description="Date when provision commenced into force."
    )
    effective_until: Optional[datetime.date] = Field(
        default=None, description="Date when provision was repealed or superseded."
    )
    legal_status: str = Field(
        default="Unknown", description="In Force, Repealed, or Uncommenced as of scenario date."
    )
    notification_ref: Optional[str] = Field(
        default=None, description="Official Gazette notification reference (e.g. S.O. 5319(E))."
    )
    source_doc_id: str = Field(..., description="Manifest document identifier (e.g. DOC-01).")
    source_url: Optional[str] = Field(
        default=None, description="Official India Code / Gazette URL."
    )
    page_number: Optional[str] = Field(
        default=None, description="Page number in official gazette publication."
    )

    def compute_content_hash(self) -> str:
        """Computes SHA-256 hash of normalized provision text."""
        normalized = self.provision_text.strip().encode("utf-8")
        return hashlib.sha256(normalized).hexdigest()
