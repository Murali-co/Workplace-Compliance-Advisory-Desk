"""Unit tests for Hybrid Search Engine (Dense + BM25 + RRF) and Proviso Expansion."""

import datetime

import pytest
from retrieval.bm25_index import BM25Index
from retrieval.hybrid_search import HybridSearchEngine


@pytest.fixture
def sample_provisions():
    return [
        {
            "provision_id": "PROV-SS2020-S53-1",
            "act": "The Code on Social Security, 2020",
            "section": "53",
            "subsection": "1",
            "clause": None,
            "provision_type": "Main Rule",
            "parent_provision": "Section 53",
            "provision_text": "Gratuity shall be payable to an employee on the termination of his employment after he has rendered continuous service for not less than five years.",
            "effective_from": datetime.date(2025, 11, 21),
            "effective_until": None,
            "legal_status": "In Force",
        },
        {
            "provision_id": "PROV-SS2020-S53-1-P2",
            "act": "The Code on Social Security, 2020",
            "section": "53",
            "subsection": "1",
            "clause": "Second Proviso",
            "provision_type": "Proviso (Statutory Exception / Waiver of 5-Year Rule)",
            "parent_provision": "Section 53(1)",
            "provision_text": "Provided further that the completion of continuous service of five years shall not be necessary where the termination of the employment of any employee is due to death or disablement or expiration of fixed term employment or happening of any such event as may be notified by the Central Government.",
            "effective_from": datetime.date(2025, 11, 21),
            "effective_until": None,
            "legal_status": "In Force",
        },
        {
            "provision_id": "PROV-PGA1972-S4-1",
            "act": "The Payment of Gratuity Act, 1972",
            "section": "4",
            "subsection": "1",
            "clause": None,
            "provision_type": "Main Rule (Historical / Repealed)",
            "parent_provision": "Section 4",
            "provision_text": "Gratuity shall be payable to an employee on the termination of his employment after he has rendered continuous service for not less than five years: on superannuation, retirement, death or disablement.",
            "effective_from": datetime.date(1972, 9, 16),
            "effective_until": datetime.date(2025, 11, 21),
            "legal_status": "Repealed by Section 164 of Code on Social Security, 2020",
        },
    ]


def test_bm25_exact_passage_resolution(sample_provisions):
    """Tests that BM25 accurately ranks exact keyword terms (e.g. 'fixed term employment')."""
    bm25 = BM25Index()
    docs = [
        {"provision_id": p["provision_id"], "text": p["provision_text"], "metadata": p}
        for p in sample_provisions
    ]
    bm25.build_index(docs)

    results = bm25.search("fixed term employment expiration", top_k=3)
    assert len(results) > 0
    top_doc_id = results[0][0]
    assert top_doc_id == "PROV-SS2020-S53-1-P2"


def test_temporal_status_resolution_post_2025(sample_provisions):
    """Tests temporal status evaluation for scenarios after 21 November 2025."""
    engine = HybridSearchEngine()
    engine._canonical_provisions_map = {p["provision_id"]: p for p in sample_provisions}

    docs = [
        {"provision_id": p["provision_id"], "text": p["provision_text"], "metadata": p}
        for p in sample_provisions
    ]
    engine.bm25_index.build_index(docs)

    # Search with scenario date post-commencement
    scenario_date = datetime.date(2026, 11, 15)
    results = engine.search(
        query="gratuity continuous service five years",
        top_k=5,
        as_of_date=scenario_date,
        expand_provisos=False,
    )

    pga_item = next(r for r in results if r["provision_id"] == "PROV-PGA1972-S4-1")
    assert "Repealed" in pga_item["temporal_status_as_of_date"]

    css_item = next(r for r in results if r["provision_id"] == "PROV-SS2020-S53-1")
    assert css_item["temporal_status_as_of_date"] == "In Force"


def test_proviso_expansion_surfaces_exceptions(sample_provisions):
    """Tests that querying the main rule automatically expands and surfaces the modifying proviso."""
    engine = HybridSearchEngine()
    engine._canonical_provisions_map = {p["provision_id"]: p for p in sample_provisions}

    docs = [
        {"provision_id": p["provision_id"], "text": p["provision_text"], "metadata": p}
        for p in sample_provisions
    ]
    engine.bm25_index.build_index(docs)

    # Query only mentions Section 53 main clause
    results = engine.search(
        query="Section 53 payment of gratuity",
        top_k=5,
        as_of_date=datetime.date(2026, 11, 15),
        expand_provisos=True,
    )

    result_ids = [r["provision_id"] for r in results]
    # Proviso expansion must pull in the Second Proviso even if user only asked about Section 53
    assert "PROV-SS2020-S53-1-P2" in result_ids
