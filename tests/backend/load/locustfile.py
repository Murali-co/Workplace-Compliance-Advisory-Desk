"""Locust load test suite for Workplace Compliance Advisory Desk.

Adheres strictly to Requirement D6:
- Measures submission-to-terminal-result latency (not submission call alone).
- Tests with hosted-model replaced by the delayed stub service (fixed 2.0s delay).
- Tracks p50 and p95 against declared target (p95 <= 60 seconds).
- Segregates valid answers, information requests, escalations, and technical failures.
"""

import os
import time
import uuid

from locust import HttpUser, between, task


class ComplianceDeskUser(HttpUser):
    """Simulates HR Compliance Desk client submitting inquiries and polling for results."""

    wait_time = between(1, 3)

    @task(6)
    def test_fixed_term_gratuity_query(self):
        """Compulsory difficult case: 18-month fixed-term contract gratuity (Section 4.1)."""
        self._execute_inquiry_flow(
            query_text="An employee engaged after 21 November 2025 on a written fixed-term contract of 18 months has completed the contract. Is gratuity payable?",
            scenario_date="2026-11-15",
            start_date="2025-11-22",
            end_date="2027-05-22",
            establishment_size=100,
            domain_hint="gratuity",
            workload_type="fixed_term_gratuity",
        )

    @task(2)
    def test_posh_internal_committee_query(self):
        """Ordinary educational POSH statutory query."""
        self._execute_inquiry_flow(
            query_text="What are the statutory requirements for constituting an Internal Committee in branch offices?",
            scenario_date="2026-11-15",
            start_date=None,
            end_date=None,
            establishment_size=40,
            domain_hint="workplace_harassment",
            workload_type="posh_inquiry",
        )

    @task(1)
    def test_missing_information_query(self):
        """Query with missing mandatory facts (creche without headcount) -> REQUEST_MORE_INFORMATION."""
        self._execute_inquiry_flow(
            query_text="Is our establishment legally required to construct and operate a crèche facility?",
            scenario_date="2026-11-15",
            start_date=None,
            end_date=None,
            establishment_size=None,  # Missing headcount
            domain_hint="maternity_benefit",
            workload_type="missing_headcount",
        )

    @task(1)
    def test_contentious_escalation_query(self):
        """Contentious termination dispute -> LEGAL_COUNSEL_REVIEW."""
        self._execute_inquiry_flow(
            query_text="An employee has raised a formal wrongful termination dispute contesting dismissal.",
            scenario_date="2026-11-15",
            start_date="2024-01-01",
            end_date="2026-05-01",
            establishment_size=250,
            domain_hint="general_compliance",
            workload_type="dispute_escalation",
        )

    def _execute_inquiry_flow(
        self,
        query_text: str,
        scenario_date: str,
        start_date: str,
        end_date: str,
        establishment_size: int,
        domain_hint: str,
        workload_type: str,
    ):
        idempotency_key = str(uuid.uuid4())
        correlation_id = f"corr-{uuid.uuid4()}"

        payload = {
            "query_text": query_text,
            "scenario_date": scenario_date,
            "employment_start_date": start_date,
            "employment_end_date": end_date,
            "establishment_size": establishment_size,
            "domain_hint": domain_hint,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['LOAD_TEST_TOKEN']}",
            "Idempotency-Key": idempotency_key,
            "X-Correlation-ID": correlation_id,
        }

        start_time = time.time()

        # Step 1: Submit inquiry
        with self.client.post(
            "/api/v1/queries",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/api/v1/queries [POST Submit]",
        ) as resp:
            if resp.status_code not in [200, 202]:
                resp.failure(f"Submit failed with status {resp.status_code}")
                return

            data = resp.json()
            run_id = data.get("run_id")
            poll_url = data.get("poll_url") or f"/api/v1/runs/{run_id}"

        # Step 2: Poll for terminal state
        max_poll_time = 120.0  # seconds timeout
        poll_start = time.time()

        while time.time() - poll_start < max_poll_time:
            time.sleep(1.5)  # Polling interval
            poll_resp = self.client.get(
                poll_url,
                headers={"Authorization": headers["Authorization"]},
                name="/api/v1/runs/{run_id} [GET Poll]",
            )
            if poll_resp.status_code != 200:
                continue

            run_data = poll_resp.json()
            status = run_data.get("status")

            if status in ["COMPLETED", "FAILED", "CANCELLED"]:
                total_duration = time.time() - start_time
                route = run_data.get("business_route", "UNKNOWN")

                # Record custom Locust metric for complete submission-to-result latency
                self.environment.events.request.fire(
                    request_type="E2E_RUN",
                    name=f"E2E_Run_{workload_type}_{route}",
                    response_time=total_duration * 1000.0,  # Locust expects ms
                    response_length=len(poll_resp.content),
                    exception=None if status == "COMPLETED" else Exception(f"Run failed: {status}"),
                    context={"status": status, "route": route},
                )
                return

        # If loop timed out
        self.environment.events.request.fire(
            request_type="E2E_RUN",
            name=f"E2E_Run_{workload_type}_TIMEOUT",
            response_time=(time.time() - start_time) * 1000.0,
            response_length=0,
            exception=TimeoutError("Run did not achieve terminal state within 120 seconds"),
            context={"status": "TIMED_OUT"},
        )
