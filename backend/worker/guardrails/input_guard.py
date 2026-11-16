"""Input guardrail defending against prompt injection and toxic content.

Adheres strictly to Requirement L4:
Defends against prompt injection on every free-text field reaching an agent or model.
"""

import re
from typing import Tuple

INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    r"disregard\s+(?:all\s+)?(?:rules|policies|guidelines)",
    r"system\s*:\s*override",
    r"you\s+are\s+now\s+(?:dan|developer\s+mode|unrestricted)",
    r"jailbreak",
    r"bypass\s+compliance",
    r"grant\s+gratuity\s+unconditionally\s+without\s+statutory\s+evidence",
    r"do\s+not\s+cite\s+any\s+law",
    r"delete\s+(?:all\s+)?database",
    r"<script.*?>",
    r"execute\s+tool\s+arbitrary",
]

COMPILED_INJECTION_REGEX = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def inspect_input_guardrail(text: str, max_characters: int = 4000) -> Tuple[bool, str]:
    """Inspects text for prompt injection attempts.

    Returns:
        (is_safe: bool, reason: str)
    """
    if not text:
        return True, "Safe"

    match = COMPILED_INJECTION_REGEX.search(text)
    if match:
        matched_pattern = match.group(0)
        return False, f"Prompt injection guardrail triggered: detected pattern '{matched_pattern}'"

    # String length bounds
    if len(text) > max_characters:
        return False, f"Input exceeds maximum allowed safety threshold of {max_characters} characters."

    return True, "Safe"
