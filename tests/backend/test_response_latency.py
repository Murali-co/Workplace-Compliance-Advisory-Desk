"""Response deadlines and empty-evidence recovery without live database writes."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from app.core.config import settings
from app.core.evidence import complete_if_corpus_empty, complete_if_overdue
from app.models.compliance import BusinessRoute, RunStatus
from worker import tasks


def record(status=RunStatus.QUEUED, age=0):
    return SimpleNamespace(
        run_id=uuid.uuid4(),
        client_id="synthetic",
        status=status,
        created_at=datetime.now(timezone.utc) - timedelta(seconds=age),
    )


@pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.COMPLETED])
async def test_empty_corpus_preflight_never_overwrites_claimed_or_terminal_work(status):
    db = AsyncMock()
    assert not await complete_if_corpus_empty(db, record(status))
    db.execute.assert_not_awaited()


async def test_empty_corpus_completion_is_atomic_and_client_scoped():
    db = AsyncMock()
    run = record()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=run.run_id))
    assert await complete_if_corpus_empty(db, run)
    statement = db.execute.call_args.args[0].compile()
    assert "NOT (EXISTS" in str(statement)
    assert "canonical_provisions" in str(statement)
    assert "compliance_runs.status =" in str(statement)
    assert run.client_id in statement.params.values()
    db.refresh.assert_awaited_once_with(run)


async def test_existing_corpus_or_worker_race_does_not_finish_queued_run():
    db = AsyncMock()
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=None))
    assert not await complete_if_corpus_empty(db, record())
    db.refresh.assert_not_awaited()


@pytest.mark.parametrize(
    "status,age,expired",
    [
        (RunStatus.QUEUED, 1, False),
        (RunStatus.QUEUED, 25, True),
        (RunStatus.RUNNING, 25, False),
        (RunStatus.RUNNING, 65, True),
        (RunStatus.COMPLETED, 120, False),
        (RunStatus.CANCELLED, 120, False),
    ],
)
async def test_response_deadlines_preserve_active_work_and_terminal_results(
    status, age, expired, monkeypatch
):
    db = AsyncMock()
    run = record(status, age)
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=run.run_id))
    monkeypatch.setattr(settings, "QUEUE_WAIT_TIMEOUT_SECONDS", 20)
    monkeypatch.setattr(settings, "RESPONSE_DEADLINE_SECONDS", 60)
    assert await complete_if_overdue(db, run) is expired
    assert db.refresh.await_count == int(expired)


def test_empty_snapshot_needs_no_retrieval_or_model(monkeypatch):
    engine = Mock(side_effect=AssertionError("Empty evidence must not initialize retrieval"))
    monkeypatch.setattr(tasks, "HybridSearchEngine", engine)
    result = tasks.reason_over_snapshot({"query_text": "Any inquiry"}, [])
    assert result["business_route"] == BusinessRoute.LEGAL_COUNSEL_REVIEW
    assert result["final_citations"] == []
    assert result["execution_steps"][0]["decision"] == "EMPTY_CORPUS"
    engine.assert_not_called()


def test_lexical_mode_responds_without_embedding_model(monkeypatch):
    from retrieval.hybrid_search import HybridSearchEngine

    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "lexical")
    vector = Mock()
    vector.query_similar.side_effect = AssertionError("Lexical mode must not load embeddings")
    engine = HybridSearchEngine(vector_store=vector)
    engine.load_corpus(
        [
            {
                "provision_id": "fixture",
                "act": "Synthetic",
                "section": "1",
                "provision_text": "Robot diagnostics daily",
            }
        ],
        index_vectors=False,
    )
    assert engine.search("robot diagnostics")[0]["provision_id"] == "fixture"
    vector.query_similar.assert_not_called()
