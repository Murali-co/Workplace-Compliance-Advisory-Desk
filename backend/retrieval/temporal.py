"""Resolve only dates/status recorded on the canonical provision."""

from datetime import date


def temporal_status(provision: dict, as_of: date | None) -> str:
    start, end = provision.get("effective_from"), provision.get("effective_until")
    start = date.fromisoformat(start) if isinstance(start, str) and start else start
    end = date.fromisoformat(end) if isinstance(end, str) and end else end
    declared = provision.get("legal_status") or "Unknown"
    if as_of:
        if start and as_of < start:
            return "Uncommenced"
        if end and as_of >= end:
            return "Repealed"
        if start and as_of >= start and (not end or as_of < end):
            if declared.lower().startswith("uncommenced"):
                return "Unknown"
            if declared.lower().startswith("repealed") and not end:
                return declared
            return "In Force"
    return provision.get("legal_status") or "Unknown"
