"""Fuse dense/BM25 ranks; resolve every expanded passage independently."""

from datetime import date
from functools import lru_cache

from app.core.config import settings
from retrieval.bm25_index import BM25Index, meaningful_terms
from retrieval.temporal import temporal_status
from retrieval.vector_store import VectorStoreManager


@lru_cache(maxsize=1)
def shared_vector_store():
    """Reuse the local encoder and Chroma connection between worker inquiries."""
    return VectorStoreManager()


def prefer_specific_sections(provisions, query):
    """Drop generic matches covered by a more specific retrieved section.

    Keep each section's modifying clauses together and preserve semantic-only
    matches when exact terminology differs. This is a relevance filter, not a
    determination of legal applicability or source validity.
    """
    query_terms = meaningful_terms(query)
    coverage = {}
    for provision in provisions:
        key = (provision["act"], provision["section"])
        coverage.setdefault(key, set()).update(
            query_terms & meaningful_terms(provision["provision_text"])
        )
    keep = {
        key
        for key, terms in coverage.items()
        if not terms or not any(terms < other for other in coverage.values())
    }
    return [p for p in provisions if (p["act"], p["section"]) in keep]


class HybridSearchEngine:
    def __init__(self, vector_store=None, bm25_index=None):
        self.vector_store = vector_store or shared_vector_store()
        self.bm25_index = bm25_index or BM25Index()
        self._canonical_provisions_map = {}

    def load_corpus(self, provisions, index_vectors=True):
        self._canonical_provisions_map = {p["provision_id"]: dict(p) for p in provisions}
        self.bm25_index.build_index(
            [
                {
                    "provision_id": p["provision_id"],
                    "text": f"{p['act']} Section {p['section']} {p.get('clause') or ''} {p['provision_text']}",
                    "metadata": p,
                }
                for p in provisions
            ]
        )
        if index_vectors:
            return self.vector_store.upsert_provisions(provisions)

    def search(
        self,
        query: str,
        top_k=5,
        as_of_date: date | None = None,
        expand_provisos=True,
        in_force_only=False,
    ):
        if top_k < 1 or not self._canonical_provisions_map:
            return []
        dense = (
            self.vector_store.query_similar(query, top_k=top_k * 2)
            if settings.RETRIEVAL_MODE == "hybrid"
            else []
        )
        # Nearest neighbours exist even for out-of-domain questions. RRF alone
        # cannot distinguish an irrelevant nearest neighbour from useful evidence.
        dense = [hit for hit in dense if hit.get("score", 0) >= settings.RETRIEVAL_MIN_DENSE_SCORE]
        lexical = self.bm25_index.search(query, top_k=top_k * 2)
        scores = {}
        for ranking in ([r["provision_id"] for r in dense], [r[0] for r in lexical]):
            for rank, pid in enumerate(ranking, 1):
                scores[pid] = scores.get(pid, 0) + 1 / (60 + rank)
        results, seen = [], set()

        def append(pid, score, reason=None):
            if pid in seen or pid not in self._canonical_provisions_map:
                return
            seen.add(pid)
            p = self._canonical_provisions_map[pid]
            status = temporal_status(p, as_of_date)
            if in_force_only and status != "In Force":
                return
            item = dict(p, rrf_score=score, temporal_status_as_of_date=status)
            if reason:
                item["expansion_reason"] = reason
            results.append(item)

        # Limit base hits, retaining all modifying clauses for each selected section.
        base_count = 0
        for pid in sorted(scores, key=scores.get, reverse=True):
            if pid in seen:
                continue
            p = self._canonical_provisions_map.get(pid)
            if not p:
                continue
            if in_force_only and temporal_status(p, as_of_date) != "In Force":
                continue
            append(pid, scores[pid])
            base_count += 1
            if expand_provisos:
                for cid, child in self._canonical_provisions_map.items():
                    if child.get("act") == p.get("act") and child.get("section") == p.get(
                        "section"
                    ):
                        append(cid, scores[pid] * 0.95, f"Related clause of {pid}")
            if base_count >= top_k:
                break
        return prefer_specific_sections(results, query)
