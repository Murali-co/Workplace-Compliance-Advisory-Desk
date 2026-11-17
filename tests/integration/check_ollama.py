"""Real local inference plus graph check with synthetic retrieval, no database writes."""

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
import httpx
from app.core.config import settings
from app.models.compliance import BusinessRoute
from llm.adapter import get_model_adapter
from retrieval.hybrid_search import HybridSearchEngine
from worker.agents.graph import build_compliance_graph
from worker.tools.corpus_search import run_search_engine


async def model_check():
    async with httpx.AsyncClient(timeout=5) as client:
        tags = (await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")).json()
    names = [m["name"] for m in tags["models"]]
    assert settings.LLM_MODEL_NAME in names, "Configured local model not installed"
    result = await get_model_adapter().generate_response(
        [
            {"role": "system", "content": "Return only JSON with key connected and boolean true."},
            {"role": "user", "content": "Test the local model connection. Return JSON."},
        ]
    )
    assert json.loads(result["content"]).get("connected") is True
    return {
        key: result[key]
        for key in ("provider", "prompt_tokens", "completion_tokens", "duration_seconds")
    }


def main():
    assert settings.LLM_PROVIDER == "ollama", "Select ollama in .env first"
    connection = asyncio.run(model_check())
    vector = Mock()
    vector.query_similar.return_value = [{"provision_id": "SYNTHETIC-ROBOT-1"}]
    engine = HybridSearchEngine(vector_store=vector)
    text = "Robotic units must submit a diagnostic report daily."
    engine.load_corpus(
        [
            {
                "provision_id": "SYNTHETIC-ROBOT-1",
                "act": "Non-legal synthetic fixture",
                "section": "1",
                "clause": None,
                "provision_text": text,
                "legal_status": "In Force",
                "effective_from": "2025-01-01",
            }
        ],
        index_vectors=False,
    )
    token = run_search_engine.set(engine)
    start = time.monotonic()
    try:
        result = build_compliance_graph().invoke(
            {
                "run_id": "ollama-synthetic-check",
                "query_text": "How often must robotic units submit diagnostic reports?",
                "scenario_date": "2026-11-16",
                "research_pass": 0,
                "business_route": None,
                "execution_steps": [],
            }
        )
    finally:
        run_search_engine.reset(token)
    if result.get("business_route") != BusinessRoute.ANSWER_WITH_CITATIONS:
        print(
            json.dumps(
                {
                    key: result.get(key)
                    for key in (
                        "business_route",
                        "route_reason",
                        "draft_claims",
                        "verification_reasons",
                        "execution_steps",
                    )
                },
                default=str,
                indent=2,
            )
        )
    assert result["business_route"] == BusinessRoute.ANSWER_WITH_CITATIONS, (
        "Local graph did not approve the supported synthetic passage"
    )
    assert result["final_advisory"] == text
    assert result["final_citations"][0]["quoted_text"] == text
    usage = [s["model_usage"] for s in result["execution_steps"] if s.get("model_usage")]
    assert len(usage) >= 2 and all(call["provider"] == "ollama-local" for call in usage)
    positive_seconds = round(time.monotonic() - start, 3)
    token = run_search_engine.set(engine)
    try:
        unrelated = build_compliance_graph().invoke(
            {
                "run_id": "ollama-unrelated-check",
                "query_text": "What is the temperature on the surface of the Moon?",
                "scenario_date": "2026-11-16",
                "research_pass": 0,
                "business_route": None,
                "execution_steps": [],
            }
        )
    finally:
        run_search_engine.reset(token)
    assert unrelated["business_route"] == BusinessRoute.LEGAL_COUNSEL_REVIEW
    assert unrelated["final_citations"] == []
    report = {
        "provider": "ollama-local",
        "model": settings.LLM_MODEL_NAME,
        "connection": connection,
        "graph": "passed",
        "graph_seconds": positive_seconds,
        "unrelated_query_rejected": True,
        "model_calls": len(usage),
        "scope": "Real local inference; synthetic in-memory retrieval. No Neon writes or full legal acceptance.",
    }
    (Path(__file__).resolve().parents[2] / "tests/evidence/ollama-connection.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
