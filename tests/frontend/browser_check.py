"""Real Chrome UI checks with explicitly synthetic HTTP fixtures.

Run with AUDIT_FRONTEND_URL pointing at a local Vite/preview server.
Does not prove Neon, hosted model, worker, or real law acceptance.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("AUDIT_FRONTEND_URL", "http://127.0.0.1:4010")
EVIDENCE = Path(__file__).resolve().parents[2] / "tests/evidence"
A = "00000000-0000-4000-8000-000000000001"
B = "00000000-0000-4000-8000-000000000002"


def result(identifier=A):
    return dict(
        run_id=identifier,
        client_id="synthetic-a",
        status="COMPLETED",
        business_route="ANSWER_WITH_CITATIONS",
        route_reason="Synthetic browser fixture; no legal conclusion.",
        advisory_text="Synthetic machinery must submit diagnostic reports. " * 12,
        citations=[
            dict(
                act="Synthetic non-legal testing statute " + "long title " * 8,
                section="999",
                clause="Test clause",
                legal_status="In Force",
                provision_id="SYNTHETIC-ONLY",
                quoted_text="Synthetic machinery must submit diagnostic reports daily.",
            )
        ],
        correlation_id="synthetic-browser",
        claim_digest="a" * 64,
        prompt_version="v2-extractive:stub",
        execution_trace=[{"step_name": "synthetic_research", "decision": "FIXTURE"}],
    )


def run():
    EVIDENCE.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        console_errors = []
        network_failures = []
        page.on(
            "console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None
        )
        page.on(
            "response",
            lambda response: (
                network_failures.append(
                    {"path": response.url.split(BASE)[-1], "status": response.status}
                )
                if response.status >= 400
                else None
            ),
        )
        page.on("pageerror", lambda error: errors.append(str(error)))
        mode = {
            "submit_fail": False,
            "feedback_fail": True,
            "running": False,
            "count": 0,
            "automatic": False,
            "not_found": False,
        }
        keys = []

        def api(route):
            path = urlsplit(route.request.url).path
            if path == "/__local_workspace":
                return route.fulfill(json={"enabled": mode["automatic"]})
            if path == "/api/v1/workspace":
                if mode["automatic"]:
                    assert "authorization" not in route.request.headers
                else:
                    assert route.request.headers.get("authorization") in (
                        "Bearer synthetic-a",
                        "Bearer synthetic-b",
                    )
                return route.fulfill(json={"client_id": "synthetic-a"})
            if path == "/ready":
                if mode.get("database_down"):
                    return route.fulfill(
                        status=503,
                        json={
                            "infrastructure_ready": False,
                            "corpus_ready": False,
                            "components": {
                                "database": {"status": False},
                                "corpus": {"status": False},
                            },
                        },
                    )
                return route.fulfill(json={"infrastructure_ready": True, "corpus_ready": True})
            if path == "/api/v1/feedback/summary":
                assert route.request.headers.get("authorization") in (
                    "Bearer synthetic-a",
                    "Bearer synthetic-b",
                )
                return route.fulfill(json={"total_feedback": 0})
            if path == "/api/v1/queries":
                keys.append(route.request.headers["idempotency-key"])
                body = route.request.post_data_json
                assert body["establishment_size"] is None
                if mode["submit_fail"]:
                    return route.fulfill(
                        status=503, json={"detail": "Synthetic queue unavailable. Retry."}
                    )
                mode["count"] += 1
                return route.fulfill(
                    status=202, json={"run_id": A if mode["count"] == 1 else B, "status": "QUEUED"}
                )
            if path.endswith("/cancel"):
                mode["running"] = False
                return route.fulfill(
                    json=dict(
                        result(B),
                        status="CANCELLED",
                        business_route=None,
                        advisory_text=None,
                        citations=[],
                        route_reason="Cancelled synthetic inquiry.",
                    )
                )
            if path.startswith("/api/v1/runs/"):
                identifier = path.rsplit("/", 1)[-1]
                if mode.get("poll_fail"):
                    return route.fulfill(
                        status=503, json={"detail": "Synthetic status unavailable"}
                    )
                if mode["not_found"] and identifier == A:
                    return route.fulfill(status=404, json={"detail": "Inquiry unavailable"})
                data = result(identifier)
                if mode["running"]:
                    data.update(
                        status="RUNNING", business_route=None, advisory_text=None, citations=[]
                    )
                return route.fulfill(json=data)
            if path == "/api/v1/feedback":
                if mode["feedback_fail"]:
                    mode["feedback_fail"] = False
                    return route.fulfill(
                        status=503, json={"detail": "Synthetic feedback unavailable. Retry."}
                    )
                return route.fulfill(status=201, json={"feedback_id": "fixture"})
            return route.fulfill(status=404, json={"detail": "Fixture not found"})

        page.route("**/__local_workspace", api)
        page.route("**/ready", api)
        page.route("**/api/v1/**", api)
        page.goto(BASE)
        expect(page.get_by_role("heading", name="Your inquiry", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Review compliance inquiry")).to_be_disabled()
        page.screenshot(path=str(EVIDENCE / "after-desktop.png"), full_page=True)
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 1000})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (
                f"Overflow at {width}px"
            )
            if width == 390:
                page.screenshot(path=str(EVIDENCE / "after-mobile.png"), full_page=True)
        page.get_by_label("Access token", exact=True).fill("synthetic-a")
        page.get_by_role("button", name="Connect", exact=True).click()
        expect(page.get_by_text("Private workspace connected")).to_be_visible()
        assert "synthetic-a" not in page.evaluate("JSON.stringify(localStorage)")
        page.get_by_label("Workplace question", exact=False).fill(
            "How often must synthetic machinery submit diagnostic reports?"
        )
        mode["submit_fail"] = True
        page.get_by_role("button", name="Review compliance inquiry").click()
        expect(page.get_by_role("alert")).to_contain_text("Synthetic queue unavailable")
        mode["submit_fail"] = False
        page.get_by_role("button", name="Review compliance inquiry").click()
        expect(page.get_by_role("heading", name="Source passages verified")).to_be_visible()
        assert keys[0] == keys[1], "Retry must preserve the idempotency key"
        expect(
            page.get_by_text("Test simulation · semantic legal verification was not performed.")
        ).to_be_visible()
        page.get_by_role("button", name="Inspect source passage", exact=False).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        assert page.evaluate('document.querySelector("dialog").contains(document.activeElement)')
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.get_by_role("button", name="View execution record").click()
        expect(page.get_by_role("dialog")).to_contain_text("synthetic_research")
        page.get_by_role("button", name="Close", exact=True).click()
        page.get_by_role("radio", name="Yes", exact=True).check()
        page.get_by_role("button", name="Send feedback").click()
        expect(page.get_by_role("alert")).to_contain_text("Synthetic feedback unavailable")
        page.get_by_role("button", name="Send feedback").click()
        expect(page.get_by_role("status")).to_contain_text("Your feedback has been saved")
        page.screenshot(path=str(EVIDENCE / "after-result-synthetic.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.screenshot(path=str(EVIDENCE / "after-result-mobile-synthetic.png"), full_page=True)
        page.reload()
        expect(page.get_by_role("button", name="Connect", exact=True)).to_be_visible()
        page.get_by_label("Access token", exact=True).fill("synthetic-a")
        page.get_by_role("button", name="Connect", exact=True).click()
        expect(page.get_by_role("heading", name="Source passages verified")).to_be_visible()
        page.get_by_label("Workplace question", exact=False).fill(
            "Another synthetic machinery diagnostic inquiry"
        )
        mode["running"] = True
        page.get_by_role("button", name="Review compliance inquiry").click()
        expect(page.get_by_role("button", name="Cancel inquiry")).to_be_visible()
        page.get_by_role("button", name="Cancel inquiry").click()
        expect(page.get_by_role("heading", name="Inquiry cancelled")).to_be_visible()
        page.get_by_role("button", name="Disconnect", exact=True).click()
        expect(page.get_by_text("A considered answer starts here.")).to_be_visible()
        assert page.get_by_text("Synthetic machinery must submit", exact=False).count() == 0
        assert not errors, errors
        assert all(
            item["status"] == 503 and item["path"] in {"/api/v1/queries", "/api/v1/feedback"}
            for item in network_failures
        ), network_failures
        assert len(network_failures) == 2, network_failures
        assert all("503" in error for error in console_errors), console_errors
        mode.update(automatic=True, not_found=True, running=False)
        auto = browser.new_page(viewport={"width": 390, "height": 844})
        auto.on("pageerror", lambda error: errors.append(str(error)))
        auto.route("**/__local_workspace", api)
        auto.route("**/ready", api)
        auto.route("**/api/v1/**", api)
        auto.add_init_script(f"localStorage.setItem('compliance:last:local:synthetic-a', '{A}')")
        auto.goto(f"{BASE}?run_id={A}")
        expect(auto.get_by_text("Local demo workspace ready")).to_be_visible()
        expect(
            auto.get_by_text(
                "That inquiry is unavailable in this workspace. You can submit a new inquiry."
            )
        ).to_be_visible()
        expect(auto.get_by_label("Access token", exact=True)).to_have_count(0)
        expect(auto.get_by_role("button", name="Review compliance inquiry")).to_be_enabled()
        assert "run_id=" not in auto.url
        assert auto.evaluate("localStorage.getItem('compliance:last:local:synthetic-a')") is None
        auto.screenshot(path=str(EVIDENCE / "missing-inquiry-recovered-mobile.png"), full_page=True)
        auto.get_by_label("Workplace question", exact=False).fill(
            "A fresh synthetic machinery reporting question"
        )
        auto.get_by_role("button", name="Review compliance inquiry").click()
        expect(auto.get_by_role("heading", name="Source passages verified")).to_be_visible()
        auto.screenshot(
            path=str(EVIDENCE / "automatic-workspace-result-mobile.png"), full_page=True
        )
        auto.reload()
        expect(auto.get_by_text("Local demo workspace ready")).to_be_visible()
        expect(auto.get_by_role("heading", name="Source passages verified")).to_be_visible()
        expect(auto.get_by_label("Access token", exact=True)).to_have_count(0)
        auto.goto(f"{BASE}?run_id=invalid")
        expect(
            auto.get_by_text("The saved inquiry link is invalid. You can submit a new inquiry.")
        ).to_be_visible()
        expect(auto.get_by_role("button", name="Review compliance inquiry")).to_be_enabled()
        assert not auto.evaluate("document.documentElement.scrollWidth > innerWidth")
        mode["poll_fail"] = True
        mode["database_down"] = True
        auto.clock.install()
        auto.goto(f"{BASE}?run_id={A}")
        expect(auto.get_by_role("alert")).to_contain_text("Synthetic status unavailable")
        expect(auto.get_by_text("The database is unavailable.", exact=False)).to_be_visible()
        expect(auto.get_by_text("The statutory corpus is empty.", exact=False)).to_have_count(0)
        expect(auto.get_by_text("Unavailable", exact=True)).to_be_visible()
        expect(auto.get_by_role("button", name="Review compliance inquiry")).to_be_enabled()
        auto.get_by_role("button", name="Start a new inquiry").click()
        expect(auto.get_by_text("A considered answer starts here.")).to_be_visible()
        assert "run_id=" not in auto.url
        mode["database_down"] = False
        auto.clock.fast_forward(16000)
        expect(auto.get_by_text("Services connected", exact=True)).to_be_visible()
        expect(auto.get_by_text("The database is unavailable.", exact=False)).to_have_count(0)
        assert not errors, errors
        report = {
            "browser": "Chrome",
            "viewport_widths": [390, 768, 1440],
            "uncaught_errors": errors,
            "expected_network_failures": network_failures,
            "console_errors": console_errors,
            "checks": [
                "disconnected empty state",
                "responsive overflow",
                "private credentials in memory",
                "submission failure/retry idempotency",
                "synthetic result",
                "citation keyboard dialog",
                "actual trace content",
                "feedback failure/retry",
                "refresh recovery",
                "run cancellation and stale terminal-response protection",
                "disconnect clears private results",
                "automatic local workspace without token entry",
                "missing inquiry releases submission and clears saved pointer",
                "automatic refresh recovery",
                "invalid saved link recovery",
                "database outage does not trap submission",
                "database readiness recovers automatically without refresh",
            ],
            "backend": "synthetic HTTP fixtures only",
        }
        (EVIDENCE / "browser-results.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        browser.close()


if __name__ == "__main__":
    run()
