"""Native Ollama contract and failure handling with isolated HTTP fixtures."""

import json

import httpx
import pytest
from app.core.config import settings
from llm import adapter


async def test_native_ollama_json_request_and_usage(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_THINK", False)
    calls = []
    real_client = httpx.AsyncClient

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {"content": '{"approved":true}'},
                "prompt_eval_count": 19,
                "eval_count": 7,
            },
        )

    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond)),
    )
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    result = await adapter.OllamaAdapter(
        base_url="http://127.0.0.1:11434/", model_name="synthetic-model"
    ).generate_response([{"role": "user", "content": "Return JSON"}])
    assert str(calls[0].url) == "http://127.0.0.1:11434/api/chat"
    payload = json.loads(calls[0].content)
    assert payload["format"] == "json" and payload["stream"] is False and payload["think"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_ctx"] == settings.OLLAMA_CONTEXT_TOKENS
    assert "authorization" not in calls[0].headers
    assert result["provider"] == "ollama-local"
    assert result["prompt_tokens"] == 19 and result["completion_tokens"] == 7
    assert json.loads(result["content"]) == {"approved": True}


@pytest.mark.parametrize(
    "status,body",
    [
        (404, {"error": "private model details"}),
        (200, {"done": False, "message": {"content": "{}"}}),
        (200, {"done": True, "message": {"content": ""}}),
        (200, {"done": True}),
    ],
)
async def test_local_failure_never_uses_simulator(monkeypatch, caplog, status, body):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        ),
    )
    with pytest.raises(adapter.ModelUnavailable, match="Local Ollama"):
        await adapter.OllamaAdapter(model_name="synthetic").generate_response([])
    assert "private model details" not in caplog.text


async def test_local_timeout_is_explicit(monkeypatch):
    real_client = httpx.AsyncClient

    def timeout(request):
        raise httpx.ReadTimeout("private prompt", request=request)

    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(timeout)),
    )
    with pytest.raises(adapter.ModelUnavailable):
        await adapter.OllamaAdapter(model_name="synthetic").generate_response([])


async def test_near_context_limit_is_not_treated_as_verified_full_evidence(monkeypatch):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "done": True,
                        "message": {"content": '{"approved":true}'},
                        "prompt_eval_count": settings.OLLAMA_CONTEXT_TOKENS,
                    },
                )
            )
        ),
    )
    with pytest.raises(adapter.ModelUnavailable):
        await adapter.OllamaAdapter(model_name="synthetic").generate_response([])


def test_factory_selects_local_provider_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "LLM_API_KEY", None)
    assert isinstance(adapter.get_model_adapter(), adapter.OllamaAdapter)


async def test_native_ollama_receives_the_explicit_response_schema(monkeypatch):
    from worker.agents.schemas import ResearchResponse

    real_client = httpx.AsyncClient
    schema = ResearchResponse.model_json_schema()
    monkeypatch.setattr(settings, "OLLAMA_THINK", True)

    def respond(request):
        assert json.loads(request.content)["format"] == schema
        assert json.loads(request.content)["think"] is True
        return httpx.Response(200, json={"done": True, "message": {"content": '{"claims":[]}'}})

    monkeypatch.setattr(
        adapter.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond)),
    )
    response = await adapter.OllamaAdapter(model_name="synthetic").generate_response(
        [], response_schema=schema
    )
    assert ResearchResponse.model_validate_json(response["content"]).claims == []


def test_research_and_verifier_response_contracts_reject_wrong_shapes():
    from pydantic import ValidationError
    from worker.agents.schemas import ResearchResponse, VerificationResponse

    with pytest.raises(ValidationError):
        ResearchResponse.model_validate({"answer": "Unsupported result without claims"})
    with pytest.raises(ValidationError):
        VerificationResponse.model_validate(
            {"approved": "true", "reasons": [], "targeted_query": ""}
        )


def test_schema_valid_unknown_evidence_id_is_rejected_without_key_error(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from worker.agents import graph

    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    model = Mock()
    model.generate_response = AsyncMock(
        return_value={"content": '{"provision_ids":["missing"]}', "provider": "ollama-local"}
    )
    monkeypatch.setattr(graph, "get_model_adapter", lambda: model)
    result = graph.model_json(
        "select evidence",
        {
            "query": "Synthetic inquiry",
            "provisions": [{"provision_id": "present", "provision_text": "Supplied text"}],
        },
    )
    assert result["claims"] == []
