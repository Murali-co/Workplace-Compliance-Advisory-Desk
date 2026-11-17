from datetime import date
from unittest.mock import Mock

import pytest
from retrieval.hybrid_search import HybridSearchEngine, prefer_specific_sections
from retrieval.temporal import temporal_status
from worker.tools import corpus_search
from worker.tools.provision_lookup import provision_lookup
from worker.tools.temporal_status_lookup import temporal_status_lookup


def passage(pid="main", **values):
    return dict(
        {
            "provision_id": pid,
            "act": "Synthetic Act A",
            "section": "1",
            "subsection": "1",
            "clause": None,
            "provision_text": "A synthetic entitlement applies subject to exceptions.",
            "legal_status": "In Force",
            "effective_from": "2025-01-01",
        },
        **values,
    )


@pytest.fixture
def engine(monkeypatch):
    vector = Mock()
    vector.query_similar.return_value = [{"provision_id": "main"}]
    engine = HybridSearchEngine(vector_store=vector)
    monkeypatch.setattr(corpus_search, "_engine_instance", engine)
    return engine


def test_expansion_keeps_exceptions_and_checks_each_date_and_act(engine):
    engine.load_corpus(
        [
            passage(),
            passage("old", clause="exception", effective_until="2025-06-01"),
            passage("other-act", act="Synthetic Act B", clause="other"),
            passage("active", clause="current exception"),
        ],
        index_vectors=False,
    )
    results = engine.search("synthetic", top_k=1, as_of_date=date(2026, 1, 1), in_force_only=True)
    assert {r["provision_id"] for r in results} == {"main", "active"}
    results = engine.search("synthetic", top_k=1, as_of_date=date(2026, 1, 1))
    assert (
        next(r for r in results if r["provision_id"] == "old")["temporal_status_as_of_date"]
        == "Repealed"
    )
    assert "other-act" not in {r["provision_id"] for r in results}


def test_unknown_or_uncommenced_status_not_silently_activated():
    assert temporal_status({"legal_status": "Uncommenced"}, date(2026, 1, 1)) == "Uncommenced"
    assert temporal_status({}, date(2026, 1, 1)) == "Unknown"
    assert temporal_status(passage(), date(2024, 1, 1)) == "Uncommenced"


def test_lookup_invalid_id_never_falls_back_to_other_coordinate(engine):
    engine.load_corpus([passage()], index_vectors=False)
    assert provision_lookup(provision_id="missing", act="Synthetic Act A", section="1") is None
    assert provision_lookup(act="Act", section="1") is None
    assert provision_lookup(act="Synthetic Act A", section="1")["provision_id"] == "main"


def test_temporal_tool_does_not_infer_blanket_act_status(engine):
    engine.load_corpus(
        [passage(), passage("future", clause="exception", effective_from="2030-01-01")],
        index_vectors=False,
    )
    assert temporal_status_lookup("Synthetic Act A", "1", "2026-01-01")["legal_status"] == "Unknown"
    assert (
        temporal_status_lookup("Synthetic Act A", "1", "2026-01-01", "future")["legal_status"]
        == "Uncommenced"
    )
    with pytest.raises(ValueError):
        temporal_status_lookup("Synthetic Act A", "1", "invalid-date")


def test_empty_corpus_does_not_call_vector_service(engine):
    assert engine.search("test") == []
    engine.vector_store.query_similar.assert_not_called()


def test_function_words_and_irrelevant_nearest_neighbours_are_not_evidence(engine, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "hybrid")
    engine.load_corpus(
        [
            passage(
                provision_text="The employer must provide maternity benefit to eligible employees."
            )
        ],
        index_vectors=False,
    )
    engine.vector_store.query_similar.return_value = [{"provision_id": "main", "score": 0.1}]
    assert engine.search("What is the temperature on the surface of the Moon?") == []
    assert engine.search("What is the maternity benefit?")[0]["provision_id"] == "main"


def test_semantic_only_match_can_be_used_when_similarity_is_sufficient(engine, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "hybrid")
    engine.load_corpus(
        [passage(provision_text="The establishment must provide a creche facility.")],
        index_vectors=False,
    )
    engine.vector_store.query_similar.return_value = [{"provision_id": "main", "score": 0.7}]
    assert engine.search("Nursery obligations")[0]["provision_id"] == "main"


def test_specific_evidence_keeps_qualifications_and_filters_generic_sections():
    rows = [
        passage(
            "core",
            section="1",
            provision_text="Gratuity applies on expiry of fixed term employment.",
        ),
        passage(
            "qualification",
            section="1",
            clause="exception",
            provision_text="Additional exceptions apply subject to qualifying service.",
        ),
        passage(
            "nomination",
            section="2",
            provision_text="An employee may nominate a person to receive gratuity.",
        ),
        passage(
            "definition",
            section="3",
            provision_text="Fixed term employment means engagement under a written contract.",
        ),
    ]
    result = prefer_specific_sections(
        rows, "Which gratuity provisions govern expiry of written fixed term employment?"
    )
    assert {p["provision_id"] for p in result} == {"core", "qualification", "definition"}
    # When nomination is the actual question it must remain available.
    assert "nomination" in {
        p["provision_id"]
        for p in prefer_specific_sections(
            rows, "How may an employee nominate a person to receive gratuity?"
        )
    }


def test_corpus_import_rejects_empty_and_conflicting_inputs(tmp_path):
    from ingestion.cli import load_provisions

    empty = tmp_path / "provisions.jsonl"
    empty.write_text("")
    with pytest.raises(ValueError, match="No provisions"):
        load_provisions(str(tmp_path), str(empty), str(tmp_path / "manifest"))
