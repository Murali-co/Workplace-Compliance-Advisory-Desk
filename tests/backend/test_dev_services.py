"""Startup waits for the actual API and never accepts a different service."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest


@pytest.fixture
def launcher(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "scripts"))
    import dev_services as module

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "RUNTIME", tmp_path / ".runtime")
    monkeypatch.setattr(module, "REGISTRY", tmp_path / ".runtime/services.json")
    monkeypatch.setattr(module, "enable_local_demo", Mock())
    monkeypatch.setattr(
        module, "dotenv_values", lambda path: {"COMPLIANCE_API_URL": "http://127.0.0.1:18110"}
    )
    monkeypatch.setattr(module.time, "sleep", Mock())
    monkeypatch.setattr(module.os, "kill", Mock())
    return module


def listener(monkeypatch, launcher, occupied):
    socket = Mock()
    socket.__enter__ = Mock(return_value=socket)
    socket.__exit__ = Mock(return_value=False)
    socket.connect_ex.return_value = 0 if occupied else 111
    monkeypatch.setattr(launcher.socket, "socket", Mock(return_value=socket))


def test_missing_pid_with_missing_saved_identity_is_not_running(monkeypatch, launcher):
    monkeypatch.setattr(launcher, "identity", lambda pid: None)
    assert not launcher.is_alive({"pid": 123, "identity": None})
    assert not launcher.is_alive({"pid": 123, "identity": "old"})


def test_runtime_source_change_invalidates_saved_configuration(launcher):
    source = launcher.ROOT / "backend/app/example.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n")
    first = launcher.configuration_hash({"setting": "same"})
    assert first == launcher.configuration_hash({"setting": "same"})
    source.write_text("value = 2\n")
    assert first != launcher.configuration_hash({"setting": "same"})


def test_start_waits_for_api_before_workers(monkeypatch, launcher):
    listener(monkeypatch, launcher, False)
    events = []

    def spawn(command, **kwargs):
        name = "api" if "uvicorn" in command else "worker" if "worker" in command else "scheduler"
        events.append(name)
        return SimpleNamespace(pid=100 + len(events), poll=lambda: None)

    def ready(port, process=None, timeout=10):
        assert events == ["api"]
        assert port == 18110
        events.append("api-ready")
        return True

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "identity", lambda pid: str(pid))
    monkeypatch.setattr(launcher, "wait_for_api", ready)
    launcher.main("start")
    assert events == ["api", "api-ready", "worker", "scheduler"]


def test_failed_api_stops_startup_before_worker(monkeypatch, launcher):
    listener(monkeypatch, launcher, False)
    spawn = Mock(return_value=SimpleNamespace(pid=100, poll=lambda: 1))
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "identity", lambda pid: "synthetic")
    monkeypatch.setattr(launcher, "wait_for_api", lambda *args: False)
    with pytest.raises(SystemExit) as failure:
        launcher.main("start")
    assert failure.value.code == 1
    assert spawn.call_count == 1


def test_unrelated_listener_is_preserved_and_startup_fails(monkeypatch, launcher):
    listener(monkeypatch, launcher, True)
    monkeypatch.setattr(launcher, "api_available", lambda port: False)
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    with pytest.raises(SystemExit, match="another service"):
        launcher.main("start")
    spawn.assert_not_called()


def test_saved_pid_without_responsive_api_does_not_report_success(monkeypatch, launcher):
    launcher.RUNTIME.mkdir()
    launcher.REGISTRY.write_text(
        json.dumps(
            {
                "api": {
                    "pid": 100,
                    "identity": "stamp",
                    "config_hash": launcher.configuration_hash(launcher.dotenv_values(None)),
                }
            }
        )
    )
    monkeypatch.setattr(launcher, "identity", lambda pid: "stamp")
    monkeypatch.setattr(launcher, "wait_for_api", lambda *args: False)
    spawn = Mock()
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    with pytest.raises(SystemExit, match="unavailable"):
        launcher.main("start")
    spawn.assert_not_called()


def test_changed_configuration_restarts_only_managed_service(monkeypatch, launcher):
    launcher.RUNTIME.mkdir()
    launcher.REGISTRY.write_text(
        json.dumps({"api": {"pid": 100, "identity": "stamp", "config_hash": "old"}})
    )
    old_alive = [True]
    monkeypatch.setattr(
        launcher,
        "identity",
        lambda pid: ("stamp" if old_alive[0] else None) if pid == 100 else str(pid),
    )
    monkeypatch.setattr(launcher.os, "kill", lambda pid, sig: old_alive.__setitem__(0, False))
    listener(monkeypatch, launcher, False)
    spawn = Mock(
        side_effect=[SimpleNamespace(pid=pid, poll=lambda: None) for pid in (101, 102, 103)]
    )
    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    monkeypatch.setattr(launcher, "wait_for_api", lambda *args: True)
    launcher.main("start")
    saved = json.loads(launcher.REGISTRY.read_text())
    assert not old_alive[0] and saved["api"]["pid"] == 101
    assert saved["api"]["config_hash"] != "old"
    assert spawn.call_count == 3


def test_wait_returns_immediately_when_api_process_exits(monkeypatch, launcher):
    probe = Mock()
    monkeypatch.setattr(launcher, "api_available", probe)
    assert not launcher.wait_for_api(18110, SimpleNamespace(poll=lambda: 1))
    probe.assert_not_called()


def test_wait_retries_until_api_is_responsive(monkeypatch, launcher):
    probe = Mock(side_effect=[False, False, True])
    monkeypatch.setattr(launcher, "api_available", probe)
    assert launcher.wait_for_api(18110, SimpleNamespace(poll=lambda: None))
    assert probe.call_count == 3


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"service": "Workplace Compliance Advisory Desk"}, True),
        ({"service": "different-project"}, False),
        ([], False),
    ],
)
def test_api_identity_is_checked_before_reusing_a_port(monkeypatch, launcher, body, expected):
    real_client = httpx.Client
    monkeypatch.setattr(
        launcher.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
        ),
    )
    assert launcher.api_available(18110) is expected
