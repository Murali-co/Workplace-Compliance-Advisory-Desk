"""Related provision lookup tool to explore provisos, exceptions, and definitions."""

from typing import Any, Dict, List

from worker.tools.corpus_search import get_search_engine


def related_provision_lookup(provision_id: str) -> List[Dict[str, Any]]:
    """Explores structural relationships for a given provision.

    Retrieves:
    1. Child provisos, exceptions, or explanations
    2. Parent charging sections
    3. Cross-referenced definitions (e.g. fixed term employment under Section 2(34)).
    """
    engine = get_search_engine()
    provisions_map = engine._canonical_provisions_map

    target = provisions_map.get(provision_id)
    if not target:
        return []

    related = []
    target_section = target.get("section")
    target_act = target.get("act", "")

    # 1. Look for provisos belonging to this section
    for p_id, p in provisions_map.items():
        if p_id == provision_id or p.get("act") != target_act:
            continue
        if p.get("act") == target_act and p.get("section") == target_section:
            related.append(
                {
                    "relation": "Modifying Proviso / Section Subclause",
                    "provision": p,
                }
            )

    # 2. Look for statutory definitions if applicable
    if "fixed term" in target.get("provision_text", "").lower() or target_section == "53":
        for p_id, p in provisions_map.items():
            if (
                p.get("act") == target_act
                and p.get("section") in {"2", "2(34)"}
                and (
                    "fixed term" in p.get("provision_text", "").lower()
                    or p.get("subsection") == "34"
                )
            ):
                related.append(
                    {
                        "relation": "Statutory Definition",
                        "provision": p,
                    }
                )

    # 3. Look for repeal section if applicable
    if target_section == "53" or "Gratuity" in target_act:
        for p_id, p in provisions_map.items():
            if p.get("act") == target_act and p.get("section") == "164":
                related.append(
                    {
                        "relation": "Repeal and Savings Provision",
                        "provision": p,
                    }
                )

    return related
