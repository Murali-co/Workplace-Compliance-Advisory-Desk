"""Corpus search tool for LangGraph agents."""

from contextvars import ContextVar
from datetime import date
from typing import Any, Dict, List, Optional

from retrieval.hybrid_search import HybridSearchEngine

run_search_engine = ContextVar("run_search_engine", default=None)
_engine_instance: Optional[HybridSearchEngine] = None


def get_search_engine() -> HybridSearchEngine:
    scoped = run_search_engine.get()
    if scoped is not None:
        return scoped
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = HybridSearchEngine()
    return _engine_instance


def corpus_search(
    query: str,
    domain: Optional[str] = None,
    top_k: int = 5,
    as_of_date_str: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Hybrid search over statutory legal corpus combining dense vectors and BM25 keywords.

    Args:
        query: Search query string (e.g. "gratuity eligibility fixed term contract").
        domain: Optional filter (gratuity, maternity, harassment).
        top_k: Max provisions to return (default 5, bounded to 10).
        as_of_date_str: Scenario reference date (YYYY-MM-DD).
    """
    top_k = min(max(1, top_k), 10)
    engine = get_search_engine()

    as_of_date = None
    if as_of_date_str:
        as_of_date = date.fromisoformat(as_of_date_str)

    results = engine.search(
        query=query,
        top_k=top_k,
        as_of_date=as_of_date,
        expand_provisos=True,
    )

    formatted = []
    for r in results:
        formatted.append(
            {
                **r,
                "provision_id": r.get("provision_id"),
                "act": r.get("act"),
                "section": r.get("section"),
                "clause": r.get("clause"),
                "provision_type": r.get("provision_type"),
                "legal_status": r.get("temporal_status_as_of_date", r.get("legal_status")),
                "provision_text": r.get("provision_text"),
                "parent_provision": r.get("parent_provision"),
                "rrf_score": round(r.get("rrf_score", 0.0), 4),
            }
        )

    return formatted
