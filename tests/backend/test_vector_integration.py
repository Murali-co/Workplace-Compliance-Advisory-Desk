"""Real isolated Chroma persistence, using a synthetic encoder (not real embeddings)."""

import hashlib

import numpy as np
import pytest
from app.core.config import settings
from retrieval.vector_store import VectorStoreManager


class SyntheticEncoder:
    def encode(self, texts, normalize_embeddings=True):
        def vector(text):
            values = np.array(list(hashlib.sha256(text.encode()).digest()[:8]), dtype=float) + 1
            return values / np.linalg.norm(values)

        return vector(texts) if isinstance(texts, str) else np.array([vector(t) for t in texts])


def test_real_chroma_round_trip_reindex_and_metadata_hash(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "CHROMA_LOCAL_PATH", str(tmp_path / "isolated-chroma"))
    monkeypatch.setattr(settings, "CHROMA_COLLECTION", "audit_synthetic_provisions")
    store = VectorStoreManager()
    store._embedder = SyntheticEncoder()
    p = {
        "provision_id": "fixture",
        "act": "Synthetic Act",
        "section": "999",
        "provision_text": "Synthetic diagnostic report.",
        "legal_status": "In Force",
        "created_at": "first",
    }
    first = store.upsert_provisions([p])
    assert first["indexed"] == 1
    p["created_at"] = "changed timestamp only"
    second = store.upsert_provisions([p])
    assert second["skipped"] == 1 and second["snapshot_hash"] == first["snapshot_hash"]
    p["legal_status"] = "Uncommenced"
    third = store.upsert_provisions([p])
    assert third["indexed"] == 1 and third["snapshot_hash"] != first["snapshot_hash"]
    found = store.query_similar("Synthetic diagnostic report", top_k=10)
    assert len(found) == 1 and found[0]["metadata"]["legal_status"] == "Uncommenced"
    assert store.collection.count() == 1


def test_chroma_http_failure_never_silently_creates_local_store(monkeypatch):
    import chromadb

    monkeypatch.setattr(settings, "CHROMA_LOCAL_PATH", None)

    def unavailable(**kwargs):
        raise ConnectionError("unavailable")

    monkeypatch.setattr(chromadb, "HttpClient", unavailable)
    with pytest.raises(ConnectionError):
        _ = VectorStoreManager().client
