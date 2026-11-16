"""Temporal status is grounded in provision metadata, never a hardcoded act date."""

from datetime import date

from retrieval.temporal import temporal_status
from worker.tools.corpus_search import get_search_engine


def temporal_status_lookup(act, section, as_of_date_str, provision_id=None):
    as_of = date.fromisoformat(as_of_date_str)
    candidates = [
        p
        for p in get_search_engine()._canonical_provisions_map.values()
        if p["act"] == act
        and str(p["section"]) == str(section)
        and (provision_id is None or p["provision_id"] == provision_id)
    ]
    statuses = {temporal_status(p, as_of) for p in candidates}
    status = next(iter(statuses)) if len(statuses) == 1 else "Unknown"
    return {
        "act": act,
        "section": section,
        "as_of_date": as_of.isoformat(),
        "legal_status": status,
        "governing": status == "In Force",
        "authority": sorted(
            {p.get("notification_ref") for p in candidates if p.get("notification_ref")}
        ),
    }
