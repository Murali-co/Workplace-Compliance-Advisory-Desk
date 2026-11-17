"""Test simulator: derive structured extracts from supplied data, never pretend inference."""

import asyncio
import json
import os
import time

from fastapi import FastAPI
from pydantic import BaseModel

STUB_DELAY_SECONDS = float(os.getenv("STUB_DELAY_SECONDS", "2"))
app = FastAPI(title="Compliance model simulator (test only)")


class ChatMessage(BaseModel):
    role: str
    content: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str | None = "stub-model"
    messages: list[ChatMessage]
    tools: list[dict] | None = None
    temperature: float | None = 0


def structured_simulation(messages):
    system = next((m.content or "" for m in messages if m.role == "system"), "")
    raw = next((m.content or "{}" for m in reversed(messages) if m.role in ("user", "human")), "{}")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {"claims": [], "simulation": True}
    provisions = {p["provision_id"]: p for p in data.get("provisions", [])}
    if "Independently audit" in system:
        claims = data.get("claims", [])
        approved = bool(claims) and all(
            c.get("assertion") == provisions.get(c.get("provision_id"), {}).get("provision_text")
            for c in claims
        )
        return {
            "approved": approved,
            "reasons": ["Deterministic simulation only; semantic entailment was not evaluated"],
            "simulation": True,
        }
    # Keyword overlap makes this a repeatable extraction fixture, not a legal model.
    import re

    stopwords = {
        "a",
        "an",
        "the",
        "is",
        "are",
        "be",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "has",
        "have",
        "what",
        "can",
        "with",
        "under",
        "after",
        "employee",
        "employment",
    }
    terms = set(re.findall(r"\w+", data.get("query", "").lower())) - stopwords
    selected = [
        p
        for p in provisions.values()
        if terms.intersection(set(re.findall(r"\w+", p["provision_text"].lower())))
    ]
    sections = {(p["act"], p["section"]) for p in selected}
    selected = [p for p in provisions.values() if (p["act"], p["section"]) in sections]
    return {
        "claims": [
            {"provision_id": p["provision_id"], "assertion": p["provision_text"]} for p in selected
        ],
        "simulation": True,
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "test-model-simulator",
        "configured_delay_seconds": STUB_DELAY_SECONDS,
    }


@app.post("/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    await asyncio.sleep(STUB_DELAY_SECONDS)
    content = json.dumps(structured_simulation(req.messages))
    return {
        "id": f"stub-{time.time_ns()}",
        "model": "test-simulator",
        "choices": [
            {"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        "simulated": True,
    }
