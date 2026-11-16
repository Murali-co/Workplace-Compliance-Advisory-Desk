"""Request fact lookup tool for agent inspection of user inputs."""

from typing import Any, Dict


def request_fact_lookup(field_name: str, state_facts: Dict[str, Any]) -> Dict[str, Any]:
    """Retrieves specific input fact fields from the active inquiry state.

    Args:
        field_name: Field to inspect (e.g. 'scenario_date', 'tenure_months', 'establishment_size').
        state_facts: Facts dictionary stored in the LangGraph state.
    """
    if field_name in state_facts:
        return {
            "field": field_name,
            "value": state_facts[field_name],
            "found": True,
        }
    return {
        "field": field_name,
        "value": None,
        "found": False,
        "message": f"Field '{field_name}' was not provided in the original inquiry.",
    }
