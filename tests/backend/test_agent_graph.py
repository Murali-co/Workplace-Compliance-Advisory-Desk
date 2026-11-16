"""Integration tests for LangGraph dual-agent reasoning and verification engine."""

import pytest
from app.models.compliance import BusinessRoute
from worker.agents.graph import build_compliance_graph
from worker.tools.corpus_search import get_search_engine


@pytest.fixture(autouse=True)
def setup_test_corpus():
    """Populates in-memory search engine with core statutory provisions."""
    engine = get_search_engine()
    provisions = [
        {
            "provision_id": "PROV-SS2020-S53-1",
            "act": "The Code on Social Security, 2020",
            "section": "53",
            "subsection": "1",
            "clause": None,
            "provision_type": "Main Rule",
            "parent_provision": "Section 53",
            "provision_text": "Gratuity shall be payable to an employee on the termination of his employment after he has rendered continuous service for not less than five years.",
            "effective_from": "2025-11-21",
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
            "effective_from": "2025-11-21",
            "effective_until": None,
            "legal_status": "In Force",
        },
        {
            "provision_id": "PROV-SS2020-S53-2-P3",
            "act": "The Code on Social Security, 2020",
            "section": "53",
            "subsection": "2",
            "clause": "Third Proviso",
            "provision_type": "Proviso (Pro-Rata Computation Mandate)",
            "parent_provision": "Section 53(2)",
            "provision_text": "Provided also that in the case of an employee employed on fixed term employment or a deceased employee, the employer shall pay gratuity on pro rata basis.",
            "effective_from": "2025-11-21",
            "effective_until": None,
            "legal_status": "In Force",
        },
        {
            "provision_id": "PROV-SS2020-S2-34",
            "act": "The Code on Social Security, 2020",
            "section": "2",
            "subsection": "34",
            "clause": "b",
            "provision_type": "Statutory Definition",
            "parent_provision": "Section 2",
            "provision_text": "fixed term employment means engagement on a written contract; employee eligible for all benefits proportionately according to period of service rendered.",
            "effective_from": "2025-11-21",
            "effective_until": None,
            "legal_status": "In Force",
        },
    ]
    engine._canonical_provisions_map = {p["provision_id"]: p for p in provisions}
    bm25_docs = [
        {"provision_id": p["provision_id"], "text": p["provision_text"], "metadata": p}
        for p in provisions
    ]
    engine.bm25_index.build_index(bm25_docs)


def test_section_4_1_difficult_case_fixed_term_gratuity():
    """Authoritative test case (Section 4.1 of assignment):

    'An employee engaged after 21 November 2025 on a written fixed-term contract
    of 18 months has completed the contract. Is gratuity payable?'

    Must resolve Section 53(1) Second Proviso and output ANSWER_WITH_CITATIONS.
    """
    graph = build_compliance_graph()

    initial_state = {
        "run_id": "test-run-4-1",
        "client_id": "test-client",
        "query_text": "An employee engaged after 21 November 2025 on a written fixed-term contract of 18 months has completed the contract. Is gratuity payable?",
        "scenario_date": "2026-11-15",
        "employment_start_date": "2025-11-22",
        "employment_end_date": "2027-05-22",
        "establishment_size": 100,
        "domain_hint": "gratuity",
        "correlation_id": "corr-4-1",
        "extracted_facts": {},
        "research_pass": 0,
        "tool_history": [],
        "retrieved_provisions": {},
        "draft_claims": [],
        "draft_advisory": None,
        "verification_verdict": None,
        "verification_reasons": [],
        "targeted_research_query": None,
        "business_route": None,
        "route_reason": None,
        "final_advisory": None,
        "final_citations": [],
        "claim_digest": None,
        "prompt_version": "v1.0",
        "execution_steps": [],
    }

    final_state = graph.invoke(initial_state)

    # Assertions
    assert final_state["business_route"] == BusinessRoute.ANSWER_WITH_CITATIONS
    assert final_state["claim_digest"] is not None
    assert len(final_state["claim_digest"]) == 64  # SHA-256

    citation_ids = [c["provision_id"] for c in final_state["final_citations"]]
    # Decisive proviso must be cited
    assert "PROV-SS2020-S53-1-P2" in citation_ids

    # Final advisory must conclude gratuity is payable
    assert "gratuity is payable" in final_state["final_advisory"].lower()
    assert "pro-rata" in final_state["final_advisory"].lower()


def test_escalation_on_termination_dispute():
    """F7: System must escalate to legal counsel on termination disputes."""
    graph = build_compliance_graph()

    initial_state = {
        "run_id": "test-dispute",
        "client_id": "test-client",
        "query_text": "An employee has filed an unlawful termination dispute alleging breach of contract.",
        "scenario_date": "2026-11-15",
        "employment_start_date": None,
        "employment_end_date": None,
        "establishment_size": 50,
        "domain_hint": "general_compliance",
        "correlation_id": "corr-dispute",
        "extracted_facts": {},
        "research_pass": 0,
        "tool_history": [],
        "retrieved_provisions": {},
        "draft_claims": [],
        "draft_advisory": None,
        "verification_verdict": None,
        "verification_reasons": [],
        "targeted_research_query": None,
        "business_route": None,
        "route_reason": None,
        "final_advisory": None,
        "final_citations": [],
        "claim_digest": None,
        "prompt_version": "v1.0",
        "execution_steps": [],
    }

    final_state = graph.invoke(initial_state)

    assert final_state["business_route"] == BusinessRoute.LEGAL_COUNSEL_REVIEW
    assert "contentious employment dispute" in final_state["route_reason"].lower()
    assert len(final_state["final_citations"]) == 0
