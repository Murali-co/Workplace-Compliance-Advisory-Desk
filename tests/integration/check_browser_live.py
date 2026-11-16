"""Repeat the exact reported inquiry through the actual local browser stack.

Creates synthetic audit-b inquiries and feedback; never changes user records.
No HTTP fixtures, HAR files or authentication headers are saved in evidence.
"""

import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import settings  # noqa: E402

QUESTION = "An employee completed an 18-month written fixed-term contract. Is gratuity payable, and which statutory provisions apply?"


def main():
    evidence = ROOT / "tests/evidence"
    headers = {
        "Authorization": "Bearer " + settings.AUTH_CLIENT_TOKENS["audit-b"].get_secret_value()
    }
    reports = []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"]
        )
        for number in (1, 2):
            context = browser.new_context(
                extra_http_headers=headers, viewport={"width": 1440, "height": 1050}
            )
            page = context.new_page()
            errors, failures = [], []
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.on(
                "response",
                lambda response: (
                    failures.append({"path": urlsplit(response.url).path, "http": response.status})
                    if response.status >= 400
                    else None
                ),
            )
            page.goto("http://127.0.0.1:4010/")
            expect(page.get_by_text("Local demo workspace ready", exact=True)).to_be_visible(
                timeout=20000
            )
            expect(page.get_by_text("Services connected", exact=True)).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Review compliance inquiry").click()
            assert not page.locator("#question").evaluate("element => element.validity.valid")
            page.get_by_label("Workplace question", exact=False).fill(QUESTION)
            page.get_by_label("Topic", exact=True).select_option("gratuity")
            page.get_by_label("Employee headcount").fill("100")
            started = time.monotonic()
            page.get_by_role("button", name="Review compliance inquiry").click()
            expect(
                page.get_by_role("heading", name="Source passages verified", exact=True)
            ).to_be_visible(timeout=180000)
            elapsed = round(time.monotonic() - started, 2)
            identifier = parse_qs(urlsplit(page.url).query)["run_id"][0]
            page.get_by_role("button", name="Inspect source passage", exact=False).first.click()
            expect(page.get_by_role("dialog")).to_be_visible()
            assert (
                page.get_by_role("link", name="Open recorded source", exact=False)
                .get_attribute("href")
                .startswith("https://")
            )
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            page.get_by_role("button", name="View execution record").click()
            expect(page.get_by_role("dialog")).to_contain_text("ollama-local")
            page.keyboard.press("Escape")
            page.reload()
            expect(
                page.get_by_role("heading", name="Source passages verified", exact=True)
            ).to_be_visible(timeout=25000)
            page.get_by_role("radio", name="Yes", exact=True).check()
            page.get_by_role("button", name="Send feedback", exact=True).click()
            expect(
                page.get_by_text("Thank you. Your feedback has been saved.", exact=True)
            ).to_be_visible(timeout=20000)
            page.screenshot(
                path=str(evidence / f"exact-inquiry-desktop-{number}.png"), full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            page.screenshot(
                path=str(evidence / f"exact-inquiry-mobile-{number}.png"), full_page=True
            )
            context.close()
            with httpx.Client(
                base_url="http://127.0.0.1:8010", headers=headers, timeout=20, trust_env=False
            ) as client:
                run = client.get("/api/v1/runs/" + identifier).json()
                ids = [item["provision_id"] for item in run["citations"]]
                assert (
                    run["prompt_version"] == "v2-extractive:ollama" and "OFFICIAL-SS2020-S53" in ids
                )
                usage = [
                    step["model_usage"]["prompt_tokens"]
                    for step in run["execution_trace"]
                    if step.get("model_usage")
                ]
            report = {
                "pass": number,
                "run_id": identifier,
                "seconds": elapsed,
                "citations": ids,
                "prompt_tokens": usage,
                "refresh_and_feedback": True,
                "mobile_no_overflow": True,
                "uncaught_errors": errors,
                "http_failures": failures,
                "passed": not errors and not failures,
            }
            reports.append(report)
            print(json.dumps(report), flush=True)
            (evidence / "exact-inquiry-browser.json").write_text(
                json.dumps(
                    {
                        "scope": "Two actual browser journeys on isolated audit-b, real Neon/Celery/Chroma/Ollama; exact screenshot question and facts, no fixtures.",
                        "results": reports,
                    },
                    indent=2,
                )
                + "\n"
            )
            assert report["passed"]
        browser.close()


if __name__ == "__main__":
    main()
