"""Prompt registry managing versioned prompt artifacts and cryptographic fingerprints."""

import hashlib
from typing import Dict, Tuple

from prompts.v1.research import RESEARCH_AGENT_SYSTEM_PROMPT
from prompts.v1.verification import VERIFICATION_AGENT_SYSTEM_PROMPT
from prompts.v2.research import RESEARCH_AGENT_SYSTEM_PROMPT as V2_RESEARCH
from prompts.v2.verification import VERIFICATION_AGENT_SYSTEM_PROMPT as V2_VERIFY

PROMPT_REGISTRY: Dict[str, Dict[str, str]] = {
    "v2-extractive": {"research": V2_RESEARCH, "verification": V2_VERIFY},
    "v1.0": {
        "research": RESEARCH_AGENT_SYSTEM_PROMPT,
        "verification": VERIFICATION_AGENT_SYSTEM_PROMPT,
    },
}


def get_prompt_bundle(version: str = "v1.0") -> Tuple[str, str, str]:
    """Retrieves prompt pair and computes SHA-256 fingerprint for safe provenance tracking.

    Returns:
        (research_prompt, verification_prompt, fingerprint_hash)
    """
    bundle = PROMPT_REGISTRY[version]
    res_prompt = bundle["research"]
    ver_prompt = bundle["verification"]

    combined = (version + ":" + res_prompt + ":" + ver_prompt).encode("utf-8")
    fingerprint = hashlib.sha256(combined).hexdigest()

    return res_prompt, ver_prompt, fingerprint
