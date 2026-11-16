"""Output guardrail filtering unauthorized judicial determinations.

Adheres strictly to Requirement L4:
Output filtering so the system cannot issue a determination it is not authorized to make.
The system produces an advisory grounded in law; it never issues binding legal opinions or judgments.
"""

import re
from typing import Tuple

UNAUTHORIZED_DETERMINATION_PATTERNS = [
    r"i\s+hereby\s+(?:order|rule|decree|adjudge)",
    r"this\s+(?:court|tribunal)\s+(?:orders|finds|sentences)",
    r"i\s+pronounce\s+(?:guilty|liable|convicted)",
    r"the\s+employer\s+is\s+hereby\s+fined",
    r"i\s+order\s+immediate\s+payment\s+of",
    r"this\s+is\s+a\s+binding\s+legal\s+ruling",
]

COMPILED_OUTPUT_REGEX = re.compile("|".join(UNAUTHORIZED_DETERMINATION_PATTERNS), re.IGNORECASE)


def filter_advisory_output(advisory_text: str) -> Tuple[str, bool]:
    """Filters generated advisory to ensure it remains non-prescriptive guidance.

    Returns:
        (sanitized_text: str, was_filtered: bool)
    """
    if not advisory_text:
        return "", False

    match = COMPILED_OUTPUT_REGEX.search(advisory_text)
    if match:
        sanitized = COMPILED_OUTPUT_REGEX.sub(
            "[Statutory advisory note: Authority rests with competent judicial forum]",
            advisory_text,
        )
        return sanitized, True

    return advisory_text, False
