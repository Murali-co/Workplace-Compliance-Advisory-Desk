"""Real local integration checks using only dedicated audit client records.

Creates named synthetic inquiries/feedback. Never deletes/resets user data.
Requires audit-a/audit-b operator credentials in ignored root .env.
"""

import asyncio
import hashlib
import json
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.api.v1.endpoints.queries import enforce_rate_limit  # noqa: E402
from app.core.config import settings  # noqa: E402
from fastapi import HTTPException  # noqa: E402


async def rate_check():
    import redis.asyncio as redis

    identity = "audit-rate-" + uuid.uuid4().hex
    original = settings.RATE_LIMIT_REQUESTS_PER_MINUTE
    settings.RATE_LIMIT_REQUESTS_PER_MINUTE = 2
    try:
        await enforce_rate_limit(identity)
        await enforce_rate_limit(identity)
        try:
            await enforce_rate_limit(identity)
        except HTTPException as error:
            assert error.status_code == 429
        else:
            raise AssertionError("Rate limit did not reject excess request")
        broker = redis.from_url(settings.REDIS_URL)
        try:
            ttl = await broker.ttl(
                "compliance:rate:" + hashlib.sha256(identity.encode()).hexdigest()
            )
            assert 0 < ttl <= 60
        finally:
            await broker.aclose()
        return {"real_redis_limiter": True, "expiry_seconds": ttl}
    finally:
        settings.RATE_LIMIT_REQUESTS_PER_MINUTE = original


def main():
    base = "http://127.0.0.1:8010"
    report = {
        "scope": "Real API/Neon/Redis/worker checks on isolated audit clients; synthetic records retained."
    }
    clients = [
        httpx.Client(
            base_url=base,
            timeout=25,
            trust_env=False,
            headers={
                "Authorization": "Bearer " + settings.AUTH_CLIENT_TOKENS[name].get_secret_value()
            },
        )
        for name in ("audit-a", "audit-b")
    ]
    a, b = clients
    try:
        assert httpx.get(base + "/api/v1/workspace", trust_env=False).status_code == 401
        assert a.get("/api/v1/workspace", headers={"X-Client-ID": "audit-b"}).status_code == 401
        assert a.post("/api/v1/queries", json={"query_text": "short"}).status_code == 422
        report["authentication_and_invalid_input"] = True
        before_b = b.get("/api/v1/feedback/summary").json()
        payload = {
            "query_text": "What is the temperature on the surface of the Moon?",
            "scenario_date": "2026-11-16",
            "domain_hint": "other",
        }
        key = "audit-idempotency-" + uuid.uuid4().hex

        def submit(_):
            response = a.post("/api/v1/queries", json=payload, headers={"Idempotency-Key": key})
            assert response.status_code in (200, 202), response.status_code
            return response.json()["run_id"]

        with ThreadPoolExecutor(max_workers=2) as pool:
            identifiers = list(pool.map(submit, range(2)))
        assert identifiers[0] == identifiers[1]
        identifier = identifiers[0]
        path = "/api/v1/runs/" + identifier
        assert (
            a.post(
                "/api/v1/queries",
                json={**payload, "query_text": "A different synthetic diagnostic question"},
                headers={"Idempotency-Key": key},
            ).status_code
            == 409
        )
        assert b.get(path).status_code == 404
        assert b.post(path + "/cancel").status_code == 404
        feedback = {
            "run_id": identifier,
            "satisfactory": True,
            "reason": "Synthetic integration check",
        }
        assert b.post("/api/v1/feedback", json=feedback).status_code == 404
        report["concurrent_idempotency_conflict_and_cross_client_isolation"] = True
        deadline = time.monotonic() + 130
        while time.monotonic() < deadline:
            response = a.get(path)
            assert response.status_code == 200
            run = response.json()
            if run["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(1)
        assert run["status"] == "COMPLETED" and not run["citations"]
        assert run["business_route"] == "LEGAL_COUNSEL_REVIEW"
        assert a.post(path + "/cancel").status_code == 409
        assert a.post("/api/v1/feedback", json=feedback).status_code == 201
        assert b.get("/api/v1/feedback/summary").json() == before_b
        assert a.get("/api/v1/feedback/summary").json()["total_feedback"] >= 1
        report["persisted_result_feedback_and_owner_scoped_summary"] = True
        cancel = a.post(
            "/api/v1/queries",
            json={
                **payload,
                "query_text": "Which provisions govern gratuity for a fixed-term employee?",
                "domain_hint": "gratuity",
            },
        )
        assert cancel.status_code == 202
        cancelled_path = "/api/v1/runs/" + cancel.json()["run_id"]
        assert a.post(cancelled_path + "/cancel").json()["status"] == "CANCELLED"
        assert a.post(cancelled_path + "/cancel").json()["status"] == "CANCELLED"
        assert a.get(cancelled_path).json()["status"] == "CANCELLED"
        report["cancellation_repeat_and_persistence"] = True
        report["cancelled_run_id"] = cancel.json()["run_id"]
        report.update(asyncio.run(rate_check()))
        report["passed"] = True
        (ROOT / "tests/evidence/real-client-flows.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))
    finally:
        for client in clients:
            client.close()


if __name__ == "__main__":
    main()
