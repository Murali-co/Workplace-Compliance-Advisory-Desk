"""Exact unambiguous statutory coordinate lookup."""

from worker.tools.corpus_search import get_search_engine


def provision_lookup(provision_id=None, act=None, section=None, clause=None, subsection=None):
    provisions = get_search_engine()._canonical_provisions_map
    if provision_id:
        p = provisions.get(provision_id)
        return dict(p) if p else None
    if not act or not section:
        return None
    matches = [
        p
        for p in provisions.values()
        if p.get("act", "").casefold() == act.casefold()
        and str(p.get("section")) == str(section)
        and (p.get("clause") or "").casefold() == (clause or "").casefold()
        and (subsection is None or str(p.get("subsection")) == str(subsection))
    ]
    return dict(matches[0]) if len(matches) == 1 else None
