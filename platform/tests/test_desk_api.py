"""GET /api/desk contract tests.

The desk endpoint is the first consumer of the section contract, so these tests
pin the envelope shape, the seven-section guarantee, and the read-only promise.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.factor_reviews import InMemoryFactorReviewRepository
from a_share_platform.adapters.memory.signals import InMemorySignalSnapshotRepository
from a_share_platform.api.app import create_app

SECTION_KEYS = (
    "data_health",
    "screen_shifts",
    "portfolio_tracking",
    "timing_shadow",
    "event_feed",
    "pending_tasks",
    "active_failures",
)


class DeskApiTest(unittest.TestCase):
    def client(self, **overrides: object) -> TestClient:
        return TestClient(create_app(**overrides))  # type: ignore[arg-type]

    def test_unconfigured_runtime_returns_all_seven_sections(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = self.client()

        response = client.get("/api/desk")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        keys = tuple(item["key"] for item in payload["data"]["sections"])
        self.assertEqual(keys, SECTION_KEYS)

    def test_envelope_carries_the_shared_response_context(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = self.client()

        payload = client.get("/api/desk").json()

        self.assertEqual(payload["context"]["data_mode"], "current_research")
        self.assertEqual(payload["context"]["deployment_stage"], "research")
        self.assertIn("as_of", payload["context"])
        self.assertIn("system_as_of", payload["context"])

    def test_unimplemented_domains_report_their_phase_blocker(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = self.client()

        sections = {
            item["key"]: item for item in client.get("/api/desk").json()["data"]["sections"]
        }

        portfolio = sections["portfolio_tracking"]
        events = sections["event_feed"]
        self.assertEqual(portfolio["status"], "unavailable")
        self.assertEqual(events["status"], "unavailable")
        self.assertEqual(
            portfolio["blockers"][0]["code"], "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED"
        )
        self.assertEqual(events["blockers"][0]["code"], "P8_EVENT_FEED_NOT_IMPLEMENTED")
        self.assertIsNone(portfolio["payload"])
        self.assertIsNone(events["payload"])

    def test_every_section_declares_status_title_and_reasons(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = self.client()

        for section in client.get("/api/desk").json()["data"]["sections"]:
            self.assertIn(
                section["status"], ("ready", "partial", "empty", "unavailable")
            )
            self.assertTrue(section["title"].strip())
            self.assertIsInstance(section["blockers"], list)
            self.assertIsInstance(section["coverage"], dict)
            if section["status"] == "unavailable":
                self.assertTrue(section["blockers"], f"{section['key']} must explain itself")
            if section["status"] == "partial":
                self.assertTrue(
                    section["coverage"] or section["blockers"],
                    f"{section['key']} is partial without declaring the gap",
                )

    def test_response_never_contains_prototype_sample_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = self.client()

        body = client.get("/api/desk").text

        for fixture in ("94.2", "贵州茅台", "600519", "五粮液", "28.1", "-1.62", "wind_terminal"):
            self.assertNotIn(fixture, body)
        self.assertNotIn("demo", body.lower())

    def test_repeated_reads_are_stable_and_do_not_mutate_state(self) -> None:
        """An ordinary refresh must be a pure read."""
        views = InMemoryExpectedReturnLedgerRepository()
        signals = InMemorySignalSnapshotRepository()
        reviews = InMemoryFactorReviewRepository()
        client = self.client(
            expected_return_repository=views,
            signal_snapshot_repository=signals,
            factor_review_repository=reviews,
        )

        first = client.get("/api/desk").json()["data"]
        second = client.get("/api/desk").json()["data"]

        first_status = [(item["key"], item["status"]) for item in first["sections"]]
        second_status = [(item["key"], item["status"]) for item in second["sections"]]
        self.assertEqual(first_status, second_status)
        self.assertEqual(views.list_views(), ())
        self.assertEqual(signals.list_snapshots(), ())
        self.assertEqual(reviews.list_reviews(), ())

    def test_openapi_documents_the_desk_endpoint(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = self.client()

        schema = client.get("/openapi.json").json()

        self.assertIn("/api/desk", schema["paths"])
        self.assertIn("get", schema["paths"]["/api/desk"])


if __name__ == "__main__":
    unittest.main()
