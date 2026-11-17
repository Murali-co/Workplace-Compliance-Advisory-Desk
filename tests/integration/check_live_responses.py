"""Submit named diagnostic inquiries using the local-demo client and measure outcomes.

These create ordinary persisted inquiries, never delete/reset corpus or user runs.
Run explicitly against a configured local API. Secrets are never printed or saved.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import settings  # noqa: E402

CASES = [
    (
        "fixed_term_gratuity",
        "An employee completed an 18-month written fixed-term contract. Is gratuity payable, and which statutory provisions apply?",
        "gratuity",
        True,
    ),
    (
        "maternity_benefit",
        "What is the maximum period of maternity benefit, and what qualifications apply?",
        "maternity_benefit",
        True,
    ),
    (
        "creche",
        "What creche facility must an establishment with 100 employees provide?",
        "maternity_benefit",
        True,
    ),
    (
        "posh_committee",
        "How must an employer constitute the Internal Committee under POSH?",
        "workplace_harassment",
        True,
    ),
    ("unrelated", "What is the temperature on the surface of the Moon?", "other", False),
]

REQUIRED_CITATIONS = {
    "fixed_term_gratuity": {"OFFICIAL-SS2020-S53"},
    "maternity_benefit": {"OFFICIAL-SS2020-S60"},
    "creche": {"OFFICIAL-SS2020-S67"},
    "posh_committee": {"OFFICIAL-POSH2013-S4"},
    "unrelated": set(),
}


def main(base_url, client_id):
    token = settings.AUTH_CLIENT_TOKENS[client_id].get_secret_value()
    results = []
    with httpx.Client(
        base_url=base_url, timeout=20, headers={"Authorization": f"Bearer {token}"}
    ) as client:
        ready = client.get("/ready").json()
        print(
            json.dumps(
                {
                    "infrastructure_ready": ready["infrastructure_ready"],
                    "corpus_ready": ready["corpus_ready"],
                }
            ),
            flush=True,
        )
        for name, query, domain, expect_citations in CASES:
            started = time.monotonic()
            submitted = client.post(
                "/api/v1/queries",
                json={
                    "query_text": query,
                    "scenario_date": "2026-11-16",
                    "domain_hint": domain,
                    "establishment_size": 100,
                    "establishment_category": "unspecified"
                    if name == "fixed_term_gratuity"
                    else "commercial_establishment",
                },
            )
            submitted.raise_for_status()
            detail = submitted.json()
            while time.monotonic() - started < 70:
                response = client.get(detail["poll_url"])
                response.raise_for_status()
                run = response.json()
                if run["status"] in ("COMPLETED", "CANCELLED", "FAILED"):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"{name}: no terminal response within 70 seconds")
            row = {
                "case": name,
                "run_id": run["run_id"],
                "status": run["status"],
                "route": run["business_route"],
                "seconds": round(time.monotonic() - started, 3),
                "citations": len(run.get("citations") or []),
                "citation_ids": [
                    citation["provision_id"] for citation in run.get("citations") or []
                ],
                "provider": run.get("prompt_version"),
                "reason": run.get("route_reason"),
                "passed": run["status"] == "COMPLETED"
                and bool(run.get("citations")) == expect_citations
                and REQUIRED_CITATIONS[name].issubset(
                    {citation["provision_id"] for citation in run.get("citations") or []}
                )
                and run.get("prompt_version") == "v2-extractive:ollama",
            }
            results.append(row)
            print(json.dumps(row), flush=True)
    path = ROOT / "tests" / "evidence" / "live-response-latency.json"
    path.write_text(
        json.dumps(
            {
                "scope": "Actual local API, Redis/Celery, Neon and Ollama; selected diagnostic questions, not exhaustive legal accuracy",
                "results": results,
            },
            indent=2,
        )
        + "\n"
    )
    if not all(row["passed"] for row in results):
        raise SystemExit(
            "Some diagnostic inquiries did not return the expected evidence; inspect the saved results."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:4010")
    parser.add_argument("--client-id", default="audit-a")
    args = parser.parse_args()
    main(args.base_url, args.client_id)
