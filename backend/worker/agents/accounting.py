"""Token usage and virtual cost accounting for compliance agent runs.

Adheres to Requirement L5:
- Attributed per step and per run.
- Reports tokens, step costs, and cost per 100 runs.
"""

from typing import Any, Dict

# Standard shadow reference pricing (USD per 1M tokens) for lightweight models
PROMPT_COST_PER_MILLION = 0.15
COMPLETION_COST_PER_MILLION = 0.60


def compute_call_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Computes virtual dollar cost for a model invocation."""
    prompt_cost = (prompt_tokens / 1_000_000.0) * PROMPT_COST_PER_MILLION
    completion_cost = (completion_tokens / 1_000_000.0) * COMPLETION_COST_PER_MILLION
    return round(prompt_cost + completion_cost, 6)


class StepAccounting:
    """Records step-level token usage and latency."""

    def __init__(self, step_name: str, agent_name: str):
        self.step_name = step_name
        self.agent_name = agent_name
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.duration_seconds = 0.0
        self.cost_usd = 0.0

    def record_usage(self, prompt_tokens: int, completion_tokens: int, duration: float):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.duration_seconds = round(duration, 4)
        self.cost_usd = compute_call_cost(prompt_tokens, completion_tokens)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_name": self.step_name,
            "agent_name": self.agent_name,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.prompt_tokens + self.completion_tokens,
            "duration_seconds": self.duration_seconds,
            "cost_usd": self.cost_usd,
        }
