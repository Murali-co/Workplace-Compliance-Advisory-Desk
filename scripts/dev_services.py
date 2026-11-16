"""Start/stop the local API, worker and scheduler together using the development venv.

Usage: .audit-venv/bin/python scripts/dev_services.py start|status|stop
Redis and Ollama must already be running. Logs and PID identities live in .runtime/.
The launcher manages only processes it started; it never kills an unrelated listener.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values
from enable_local_demo import enable_local_demo

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
REGISTRY = RUNTIME / "services.json"


def identity(pid):
    try:
        # Start time prevents a recycled PID from being treated as our process.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return None if fields[0] == "Z" else fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def is_alive(entry):
    current = identity(entry["pid"])
    return current is not None and current == entry.get("identity")


def api_available(port):
    """Check process identity over HTTP, independently of DB/model readiness."""
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            response = client.get(f"http://127.0.0.1:{port}/")
            data = response.json()
            return (
                response.status_code == 200
                and isinstance(data, dict)
                and data.get("service") == "Workplace Compliance Advisory Desk"
            )
    except (httpx.HTTPError, ValueError):
        return False


def wait_for_api(port, process=None, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        if api_available(port):
            return True
        time.sleep(0.1)
    return False


def configuration_hash(env):
    # Store only a digest so stale processes cannot silently retain old settings.
    digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode())
    for directory in ("app", "worker", "retrieval", "llm", "prompts"):
        for path in sorted((ROOT / "backend" / directory).rglob("*.py")):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def stop_managed(entry):
    if not is_alive(entry):
        return True
    os.kill(entry["pid"], signal.SIGTERM)
    until = time.monotonic() + 15
    while is_alive(entry) and time.monotonic() < until:
        time.sleep(0.1)
    return not is_alive(entry)


def main(action):
    if action == "start":
        enable_local_demo(ROOT / ".env")
    env = dotenv_values(ROOT / ".env")
    config_hash = configuration_hash(env)
    api_port = urlsplit(env.get("COMPLIANCE_API_URL") or "http://127.0.0.1:8010").port or 8010
    RUNTIME.mkdir(exist_ok=True)
    registry = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    commands = {
        "api": [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        "worker": [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "worker.celery_app",
            "worker",
            "--loglevel=INFO",
            f"--concurrency={env.get('LOCAL_WORKER_CONCURRENCY') or '1'}",
            "--hostname=local-compliance@%h",
        ],
        "scheduler": [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "worker.celery_app",
            "beat",
            "--loglevel=INFO",
            f"--schedule={RUNTIME / 'celerybeat'}",
        ],
    }
    for name, command in commands.items():
        entry = registry.get(name)
        alive = bool(entry and is_alive(entry))
        if action == "stop":
            if alive:
                print(f"{name}: {'stopped' if stop_managed(entry) else 'still stopping'}")
            else:
                print(f"{name}: stopped")
            continue
        if action == "status":
            responding = alive and (name != "api" or api_available(api_port))
            print(f"{name}: {'running' if responding else 'stopped or unavailable'}")
            continue
        if alive and entry.get("config_hash") != config_hash:
            print(f"{name}: reloading changed configuration or code", flush=True)
            if not stop_managed(entry):
                raise SystemExit(f"{name}: still draining work; retry startup after it stops")
            alive = False
        if alive:
            if name == "api" and not wait_for_api(api_port):
                raise SystemExit(
                    f"api: process exists but port {api_port} is unavailable; inspect .runtime/api.log"
                )
            print(f"{name}: running")
            continue
        if name == "api":
            with socket.socket() as listener:
                if listener.connect_ex(("127.0.0.1", api_port)) == 0:
                    if not api_available(api_port):
                        raise SystemExit(
                            f"api: port {api_port} belongs to another service; existing process left unchanged"
                        )
                    print(f"api: existing compliance API ready on port {api_port}")
                    continue
        with (RUNTIME / f"{name}.log").open("ab") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT / "backend",
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
        registry[name] = {
            "pid": process.pid,
            "identity": identity(process.pid),
            "config_hash": config_hash,
        }
        REGISTRY.write_text(json.dumps(registry, indent=2) + "\n")
        if name == "api":
            ready = wait_for_api(api_port, process)
        else:
            time.sleep(0.2)
            ready = process.poll() is None
        print(
            f"{name}: {'ready' if ready else 'failed; see .runtime/' + name + '.log'}",
            flush=True,
        )
        if not ready:
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    main(parser.parse_args().action)
