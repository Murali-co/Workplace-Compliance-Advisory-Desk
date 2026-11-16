"""Read-only API probes and real HTTP simulator graph check with synthetic corpus."""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import httpx
from app.core.config import settings
from app.models.compliance import BusinessRoute
from retrieval.hybrid_search import HybridSearchEngine
from worker.agents.graph import build_compliance_graph
from worker.tools.corpus_search import run_search_engine


async def probes():
    async with httpx.AsyncClient(timeout=10) as client:
        results = {}
        for path in ("/", "/health", "/ready", "/metrics/", "/api/v1/feedback/summary"):
            response = await client.get("http://127.0.0.1:8100" + path)
            results[path] = response.status_code
            if path == "/ready":
                assert (
                    response.status_code == 503 and response.json()["infrastructure_ready"] is False
                )
                assert "password" not in response.text.lower()
            if path == "/health":
                assert response.status_code == 200
            if path == "/api/v1/feedback/summary":
                assert response.status_code in (401, 503)
        return results


def main():
    results = asyncio.run(probes())
    settings.STUB_SERVICE_URL = "http://127.0.0.1:8101"
    settings.LLM_PROVIDER = "stub"
    settings.STUB_DELAY_SECONDS = 0
    vector = Mock()
    vector.query_similar.return_value = [{"provision_id": "SYNTHETIC-999"}]
    engine = HybridSearchEngine(vector_store=vector)
    engine.load_corpus(
        [
            {
                "provision_id": "SYNTHETIC-999",
                "act": "Non-legal synthetic fixture",
                "section": "999",
                "clause": None,
                "provision_text": "Robotic diagnostic reports are required daily.",
                "legal_status": "In Force",
                "effective_from": "2025-01-01",
            }
        ],
        index_vectors=False,
    )
    token = run_search_engine.set(engine)
    try:
        state = build_compliance_graph().invoke(
            {
                "run_id": "synthetic-http-check",
                "query_text": "How often are robotic diagnostic reports required?",
                "scenario_date": "2026-01-01",
                "research_pass": 0,
                "business_route": None,
                "execution_steps": [],
            }
        )
        assert state["business_route"] == BusinessRoute.ANSWER_WITH_CITATIONS
        assert (
            state["final_citations"][0]["quoted_text"]
            == "Robotic diagnostic reports are required daily."
        )
        assert len(state["claim_digest"]) == 64
        steps = [s for s in state["execution_steps"] if s.get("model_usage")]
        assert len(steps) == 2 and all(
            s["model_usage"]["provider"] == "delayed-stub" for s in steps
        )
    finally:
        run_search_engine.reset(token)
    report = {
        "api_read_only_probes": results,
        "graph_http_simulator": "passed",
        "model": "test simulator, not hosted semantic inference",
        "retrieval": "synthetic dense double + real lexical index; not actual embeddings",
        "database": "not configured; readiness correctly fails",
    }
    (Path(__file__).resolve().parents[2] / "tests/evidence/local-boundaries.json").write_text(
        json.dumps(report, indent=2)
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
