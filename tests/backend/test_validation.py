"""Unit tests for Pydantic schema validation and cross-field date constraints."""

import datetime

import pytest
from app.schemas.compliance import ComplianceQueryRequest
from pydantic import ValidationError


def test_valid_compliance_query_request():
    """Tests that a fully specified valid inquiry passes validation."""
    req = ComplianceQueryRequest(
        query_text="Is gratuity payable to fixed-term workers after 18 months under the 2020 Code?",
        scenario_date=datetime.date(2026, 11, 15),
        employment_start_date=datetime.date(2025, 11, 22),
        employment_end_date=datetime.date(2027, 5, 22),
        establishment_size=120,
        domain_hint="gratuity",
        establishment_category="commercial_establishment",
    )
    assert req.establishment_size == 120
    assert req.domain_hint == "gratuity"
    assert len(req.compute_payload_hash()) == 64


def test_tolerates_unknown_establishment_details():
    """Requirement: Unknown establishment details are not automatically malformed."""
    req = ComplianceQueryRequest(
        query_text="What are the statutory guidelines regarding internal complaints committee?",
        scenario_date=datetime.date(2026, 11, 15),
    )
    assert req.employment_start_date is None
    assert req.employment_end_date is None
    assert req.establishment_size is None
    assert req.domain_hint is None


def test_rejects_query_text_too_short():
    """Enforces boundary string length validation (min 10 chars)."""
    with pytest.raises(ValidationError) as exc:
        ComplianceQueryRequest(
            query_text="Too short",
            scenario_date=datetime.date(2026, 11, 15),
        )
    assert "at least 10 characters" in str(exc.value)


def test_rejects_employment_start_after_end_date():
    """Cross-field check: employment start date cannot be after end date."""
    with pytest.raises(ValidationError) as exc:
        ComplianceQueryRequest(
            query_text="Valid length inquiry text about employment contracts.",
            scenario_date=datetime.date(2026, 11, 15),
            employment_start_date=datetime.date(2026, 5, 1),
            employment_end_date=datetime.date(2025, 5, 1),  # End before start
        )
    assert "cannot be after employment_end_date" in str(exc.value)


def test_rejects_employment_start_in_future_relative_to_scenario():
    """Cross-field check: employment start date cannot be after scenario date."""
    with pytest.raises(ValidationError) as exc:
        ComplianceQueryRequest(
            query_text="Valid length inquiry text about future employment.",
            scenario_date=datetime.date(2026, 11, 15),
            employment_start_date=datetime.date(2027, 1, 1),  # In future
        )
    assert "cannot be in the future relative to scenario_date" in str(exc.value)


def test_payload_hash_determinism():
    """Tests that identical inputs yield identical SHA-256 hashes."""
    req1 = ComplianceQueryRequest(
        query_text="Test query for deterministic payload hashing.",
        scenario_date=datetime.date(2026, 11, 15),
        establishment_size=50,
    )
    req2 = ComplianceQueryRequest(
        query_text="Test query for deterministic payload hashing.",
        scenario_date=datetime.date(2026, 11, 15),
        establishment_size=50,
    )
    assert req1.compute_payload_hash() == req2.compute_payload_hash()
