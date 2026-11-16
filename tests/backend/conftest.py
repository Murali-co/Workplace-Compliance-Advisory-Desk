"""Legacy graph/retrieval tests use synthetic model and dense boundaries.

These tests exercise orchestration and lexical retrieval. They do not prove the
real embedding/model integrations. No unit test writes the configured corpus.
"""

import pytest


@pytest.fixture(autouse=True)
def isolate_legacy_boundaries(request, monkeypatch):
    if request.node.path.name not in {"test_agent_graph.py", "test_hybrid_search.py"}:
        return
    from retrieval.vector_store import VectorStoreManager

    monkeypatch.setattr(VectorStoreManager, "query_similar", lambda *a, **kw: [])
    if request.node.path.name == "test_agent_graph.py":
        import json

        from retrieval.hybrid_search import HybridSearchEngine
        from stub.main import ChatMessage, structured_simulation
        from worker.agents import graph
        from worker.tools import corpus_search

        monkeypatch.setattr(corpus_search, "_engine_instance", HybridSearchEngine())

        def simulated_model(prompt, data):
            return structured_simulation(
                [
                    ChatMessage(role="system", content=prompt),
                    ChatMessage(role="user", content=json.dumps(data, default=str)),
                ]
            )

        monkeypatch.setattr(graph, "model_json", simulated_model)
