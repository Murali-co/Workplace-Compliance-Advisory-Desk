"""Negative-path tests for unsupported claims, outages, payload changes and leases."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from app.core.config import settings
from app.models.compliance import BusinessRoute, RunStatus
from llm import adapter
from retrieval.hybrid_search import HybridSearchEngine
from worker.agents import graph
from worker.tasks import can_claim, owns_attempt
from worker.tools import corpus_search


@pytest.fixture
def state(monkeypatch):
    vector = Mock()
    vector.query_similar.return_value = [{"provision_id": "fixture"}]
    engine = HybridSearchEngine(vector_store=vector)
    engine.load_corpus(
        [
            {
                "provision_id": "fixture",
                "act": "Synthetic Act",
                "section": "1",
                "clause": None,
                "provision_text": "Robotic units must submit a diagnostic report daily.",
                "legal_status": "In Force",
                "effective_from": "2025-01-01",
            }
        ],
        index_vectors=False,
    )
    monkeypatch.setattr(corpus_search, "_engine_instance", engine)
    p = dict(engine._canonical_provisions_map["fixture"], legal_status_temporal="In Force")
    return {
        "run_id": "fixture",
        "query_text": "How frequently must robotic units submit diagnostic reports?",
        "scenario_date": "2026-01-01",
        "research_pass": 3,
        "draft_claims": [
            {
                "claim_id": "1",
                "provision_id": "fixture",
                "assertion": p["provision_text"],
                "verified": False,
            }
        ],
        "retrieved_provisions": {"fixture": p},
        "execution_steps": [],
        "extracted_facts": {},
    }


@pytest.mark.parametrize("damage", ["assertion", "missing", "uncommenced", "duplicate"])
def test_verifier_never_approves_unsupported_claims(state, monkeypatch, damage):
    if damage == "assertion":
        state["draft_claims"][0]["assertion"] = "Robotic units never need diagnostic reports."
    elif damage == "missing":
        state["draft_claims"][0]["provision_id"] = "not-canonical"
    elif damage == "uncommenced":
        state["retrieved_provisions"]["fixture"]["legal_status_temporal"] = "Uncommenced"
    else:
        state["draft_claims"] *= 2
    model = Mock(side_effect=AssertionError("Invalid claims must fail before a model call"))
    monkeypatch.setattr(graph, "model_json", model)
    result = graph.verification_agent_node(state)
    assert result["verification_verdict"] == "ESCALATE"
    assert result["business_route"] == BusinessRoute.LEGAL_COUNSEL_REVIEW
    assert result["final_citations"] == []
    model.assert_not_called()


def test_approved_payload_cannot_be_changed_after_verification(state, monkeypatch):
    monkeypatch.setattr(graph, "model_json", lambda *args: {"approved": True})
    state.update(graph.verification_agent_node(state))
    assert graph.final_render_node(state)["business_route"] == BusinessRoute.ANSWER_WITH_CITATIONS
    state["draft_claims"][0]["assertion"] = "Changed after verification"
    assert graph.final_render_node(state)["business_route"] == BusinessRoute.LEGAL_COUNSEL_REVIEW


def test_unrelated_query_never_gets_fixed_term_advice(state, monkeypatch):
    import json

    from stub.main import ChatMessage, structured_simulation

    def model(prompt, data):
        return structured_simulation(
            [
                ChatMessage(role="system", content=prompt),
                ChatMessage(role="user", content=json.dumps(data, default=str)),
            ]
        )

    monkeypatch.setattr(graph, "model_json", model)
    state.update(
        query_text="What is the lunar surface temperature?", research_pass=0, business_route=None
    )
    result = graph.build_compliance_graph().invoke(state)
    assert result["business_route"] == BusinessRoute.LEGAL_COUNSEL_REVIEW
    assert result["research_pass"] == 3
    assert result["final_citations"] == []
    assert "18 months" not in result["final_advisory"]


def test_claim_lease_and_attempt_fencing():
    now = datetime.now(timezone.utc)
    run = SimpleNamespace(
        status=RunStatus.QUEUED, lease_expires_at=None, active_attempt_id="attempt-a"
    )
    assert can_claim(run, now)
    run.status = RunStatus.RUNNING
    run.lease_expires_at = now + timedelta(seconds=30)
    assert not can_claim(run, now)
    assert owns_attempt(run, "attempt-a") and not owns_attempt(run, "attempt-b")
    run.lease_expires_at = now - timedelta(seconds=1)
    assert can_claim(run, now)
    run.status = RunStatus.CANCELLED
    assert not can_claim(run, now) and not owns_attempt(run, "attempt-a")


async def test_hosted_outage_raises_without_stub_fallback(monkeypatch, caplog):
    real_client = httpx.AsyncClient

    def fail(request):
        return httpx.Response(503, text="private prompt token sensitive")

    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(fail)),
    )
    adapter.provider_circuit_breaker.record_success()
    model = adapter.HostedProviderAdapter(
        api_key="fixture-secret", base_url="https://model.invalid", model_name="fixture"
    )
    with pytest.raises(adapter.ModelUnavailable):
        await model.generate_response([{"role": "user", "content": "private user data"}])
    assert adapter.provider_circuit_breaker.failure_count == 1
    assert (
        "sensitive" not in caplog.text
        and "fixture-secret" not in caplog.text
        and "private user data" not in caplog.text
    )


async def test_missing_hosted_configuration_is_not_success(monkeypatch):
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    monkeypatch.setattr(settings, "LLM_BASE_URL", None)
    monkeypatch.setattr(settings, "LLM_MODEL_NAME", None)
    with pytest.raises(adapter.ModelUnavailable, match="incomplete"):
        await adapter.HostedProviderAdapter().generate_response([])


async def test_malformed_provider_body_rejected(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": []}))
        ),
    )
    with pytest.raises(adapter.ModelUnavailable):
        await adapter.DelayedStubAdapter(delay_seconds=0).generate_response([])


def test_verifier_input_contains_evidence_without_retrieval_bookkeeping(state, monkeypatch):
    state["retrieved_provisions"]["fixture"]["rrf_score"] = 0.01
    state["extracted_facts"]["establishment_size"] = None

    def verify(prompt, data):
        assert data["scenario_date"] == state["scenario_date"]
        assert "establishment_size" not in data["facts"]
        assert "verified" not in data["claims"][0]
        assert "rrf_score" not in data["provisions"][0]
        assert data["provisions"][0]["legal_status_temporal"] == "In Force"
        assert data["claims"][0]["assertion"] == data["provisions"][0]["provision_text"]
        return {"approved": True}

    monkeypatch.setattr(graph, "model_json", verify)
    result = graph.verification_agent_node(state)
    assert result["verification_verdict"] == "APPROVED"
