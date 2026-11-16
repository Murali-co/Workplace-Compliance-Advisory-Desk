"""Local bootstrap preserves connection strings and existing client credentials."""

import io
import json
from pathlib import Path

import pytest
from dotenv import dotenv_values


@pytest.fixture
def prepare(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    from scripts.enable_local_demo import enable_local_demo

    return enable_local_demo


def test_local_setup_preserves_database_and_reviewers_and_is_idempotent(tmp_path, prepare):
    path = tmp_path / ".env"
    original = 'DATABASE_URL="postgresql://synthetic:password@fixture.invalid/db?sslmode=require"\nAUTH_CLIENT_TOKENS={"reviewer":"existing-key"}\nLLM_PROVIDER=ollama\n'
    path.write_text(original)
    prepare(path)
    settings = dotenv_values(path)
    clients = json.loads(settings["AUTH_CLIENT_TOKENS"])
    assert clients["reviewer"] == "existing-key"
    assert len(clients["local-demo"]) >= 32
    assert settings["DATABASE_URL"] == dotenv_values(stream=io.StringIO(original))["DATABASE_URL"]
    assert settings["LLM_PROVIDER"] == "ollama"
    assert settings["LOCAL_DEMO_ENABLED"] == "true"
    before = path.read_text()
    prepare(path)
    assert path.read_text() == before
    assert path.stat().st_mode & 0o777 == 0o600


def test_production_cannot_enable_automatic_access(tmp_path, prepare):
    path = tmp_path / ".env"
    before = 'APP_ENV=production\nAUTH_CLIENT_TOKENS={"reviewer":"existing-key"}\n'
    path.write_text(before)
    with pytest.raises(ValueError, match="disabled"):
        prepare(path)
    assert path.read_text() == before


def test_malformed_client_settings_are_not_replaced(tmp_path, prepare):
    path = tmp_path / ".env"
    before = "AUTH_CLIENT_TOKENS=malformed\nDATABASE_URL=unchanged\n"
    path.write_text(before)
    with pytest.raises(ValueError, match="preserved"):
        prepare(path)
    assert path.read_text() == before
