"""Prepare localhost demo access without exposing keys or replacing database settings."""

import json
import secrets
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def enable_local_demo(path: Path):
    if not path.exists():
        path.write_text((ROOT / ".env.example").read_text())
    values = dotenv_values(path)
    if values.get("APP_ENV") == "production":
        raise ValueError("Automatic local demo access is disabled for production.")
    try:
        clients = json.loads(values.get("AUTH_CLIENT_TOKENS") or "{}")
    except ValueError:
        raise ValueError(
            "Client access configuration is invalid; existing settings preserved."
        ) from None
    if not isinstance(clients, dict) or any(
        not isinstance(value, str) for value in clients.values()
    ):
        raise ValueError("Client access configuration is invalid; existing settings preserved.")
    if not clients.get("local-demo"):
        clients["local-demo"] = secrets.token_urlsafe(32)
    updates = {
        "AUTH_CLIENT_TOKENS": json.dumps(clients, separators=(",", ":")),
        "LOCAL_DEMO_ENABLED": "true",
        "LOCAL_DEMO_CLIENT_ID": "local-demo",
        "COMPLIANCE_API_URL": values.get("COMPLIANCE_API_URL") or "http://127.0.0.1:8010",
    }
    lines = path.read_text().splitlines()
    seen = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates:
            lines[i] = key + "=" + updates[key]
            seen.add(key)
    lines.extend(key + "=" + value for key, value in updates.items() if key not in seen)
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)


if __name__ == "__main__":
    enable_local_demo(ROOT / ".env")
    print(
        "Local demo access prepared. Existing database and other client settings preserved; no key displayed."
    )
