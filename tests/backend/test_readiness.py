"""Dependency outage probes use doubles; live read-only results are separate evidence."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from app.api.v1.endpoints import health
from app.core.config import Settings, settings
from fastapi import Response
from pydantic import SecretStr


async def test_chroma_failure_sets_http_503_and_redacts_details(monkeypatch):
    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "hybrid")
    db = AsyncMock()
    db.execute.return_value = Mock(scalar=Mock(return_value=2))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(health, "async_session_maker", session)
    broker = AsyncMock()
    monkeypatch.setattr(health.redis, "from_url", lambda *a, **kw: broker)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        health.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda req: httpx.Response(500, text="private password"))
        ),
    )
    monkeypatch.setattr(settings, "AUTH_CLIENT_TOKENS", {"test": SecretStr("synthetic")})
    response = Response()
    result = await health.readiness_check(response)
    assert response.status_code == 503
    assert result.infrastructure_ready is False
    assert result.corpus_ready is True
    assert result.components["chroma"].status is False
    assert "password" not in result.model_dump_json()
    broker.aclose.assert_awaited_once()


async def test_missing_worker_fails_readiness_even_when_broker_is_up(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = Mock(scalar=Mock(return_value=48))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(health, "async_session_maker", session)
    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "lexical")
    monkeypatch.setattr(settings, "AUTH_CLIENT_TOKENS", {"test": SecretStr("synthetic")})
    broker = AsyncMock()
    broker.get.return_value = None
    monkeypatch.setattr(health.redis, "from_url", lambda *a, **kw: broker)
    response = Response()
    result = await health.readiness_check(response)
    assert response.status_code == 503
    assert result.components["redis"].status is True
    assert result.components["worker"].status is False
    assert result.corpus_ready is True


async def test_database_cleanup_timeout_does_not_leave_corpus_marked_ready(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = Mock(scalar=Mock(return_value=48))

    @asynccontextmanager
    async def session():
        yield db
        raise TimeoutError("Private connection cleanup details")

    monkeypatch.setattr(health, "async_session_maker", session)
    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "lexical")
    monkeypatch.setattr(settings, "AUTH_CLIENT_TOKENS", {"test": SecretStr("synthetic")})
    monkeypatch.setattr(health.redis, "from_url", lambda *a, **kw: AsyncMock())
    response = Response()
    result = await health.readiness_check(response)
    assert response.status_code == 503
    assert result.components["database"].status is False
    assert result.components["corpus"].status is False
    assert result.corpus_ready is False
    assert "Private" not in result.model_dump_json()


@pytest.mark.parametrize("tokens", [{"a": "same", "b": "same"}, {"a": ""}, {"x" * 129: "value"}])
def test_client_configuration_rejects_ambiguous_or_invalid_identity(tokens):
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as error:
        Settings(AUTH_CLIENT_TOKENS=tokens, _env_file=None)
    assert "input_value" not in str(error.value)


def test_unknown_prompt_version_is_explicit_failure():
    from prompts.registry import get_prompt_bundle

    with pytest.raises(KeyError):
        get_prompt_bundle("nonexistent")
    research, verification, fingerprint = get_prompt_bundle("v2-extractive")
    assert "untrusted" in research and "Independently audit" in verification
    assert len(fingerprint) == 64
