import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.factor_reviews import InMemoryFactorReviewRepository
from a_share_platform.adapters.memory.signals import InMemorySignalSnapshotRepository
from a_share_platform.adapters.postgres.expected_return import (
    PostgresExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.postgres.signals import PostgresSignalSnapshotRepository
from a_share_platform.api.app import create_app
from a_share_platform.application.signal_snapshots import SignalSnapshotLedgerService
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from tests.test_signal_snapshot_ledger import snapshot_for
from tests.test_signal_snapshots import approved_factor_package, investment_view


class ResearchWorkspaceApiTest(unittest.TestCase):
    def repositories(self):
        return (
            InMemoryExpectedReturnLedgerRepository(),
            InMemorySignalSnapshotRepository(),
            InMemoryFactorReviewRepository(),
        )

    def test_unconfigured_runtime_returns_professional_unavailable_envelope(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            client = TestClient(create_app())

        response = client.get("/api/research/workspace")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["status"], "unavailable")
        self.assertIsNone(payload["data"]["screen"])
        self.assertIsNone(payload["data"]["investment_view"])
        self.assertEqual(payload["context"]["data_mode"], "current_research")
        self.assertEqual(payload["context"]["deployment_stage"], "research")
        blocker_codes = {item["code"] for item in payload["data"]["blockers"]}
        self.assertIn("investment_view_store_unavailable", blocker_codes)
        self.assertIn("signal_snapshot_store_unavailable", blocker_codes)
        self.assertNotIn("demo", str(payload).lower())

    def test_ready_projection_preserves_exact_bindings_and_security_filter(self) -> None:
        views, signals, reviews = self.repositories()
        view = investment_view()
        snapshot = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        views.append_view(view)
        SignalSnapshotLedgerService(signals).record_snapshot(snapshot)
        reviews.save_review(review)
        client = TestClient(
            create_app(
                expected_return_repository=views,
                signal_snapshot_repository=signals,
                factor_review_repository=reviews,
            )
        )

        response = client.get(
            "/api/research/workspace",
            params={"security_id": view.security_id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["data"]["status"], "ready")
        self.assertEqual(payload["data"]["investment_view"]["view_id"], view.view_id)
        self.assertEqual(
            payload["data"]["alpha_model"]["model"]["environment_id"],
            view.environment_id,
        )
        self.assertIsNone(payload["data"]["investment_view"]["versions"]["artifact_id"])

    def test_unknown_security_does_not_fall_back_and_forward_scope_does_not_leak(self) -> None:
        views, signals, reviews = self.repositories()
        views.append_view(investment_view())
        SignalSnapshotLedgerService(signals).record_snapshot(snapshot_for(ApprovalScope.SHADOW))
        client = TestClient(
            create_app(
                expected_return_repository=views,
                signal_snapshot_repository=signals,
                factor_review_repository=reviews,
            )
        )

        response = client.get(
            "/api/research/workspace",
            params={"security_id": "security:unknown"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertIsNone(payload["screen"])
        self.assertIsNone(payload["investment_view"])
        self.assertEqual(payload["alpha_model"]["status"], "unavailable")

    def test_query_parameters_cannot_promote_server_owned_run_context(self) -> None:
        views, signals, reviews = self.repositories()
        client = TestClient(
            create_app(
                expected_return_repository=views,
                signal_snapshot_repository=signals,
                factor_review_repository=reviews,
            )
        )

        for params in (
            {"data_mode": "strict_historical"},
            {"deployment_stage": "shadow"},
        ):
            with self.subTest(params=params):
                response = client.get("/api/research/workspace", params=params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["type"], "run_context_override_denied")

    def test_openapi_exposes_research_workspace_as_read_only(self) -> None:
        views, signals, reviews = self.repositories()
        client = TestClient(
            create_app(
                expected_return_repository=views,
                signal_snapshot_repository=signals,
                factor_review_repository=reviews,
            )
        )

        operations = client.get("/openapi.json").json()["paths"]["/api/research/workspace"]

        self.assertEqual(set(operations), {"get"})
        self.assertEqual(
            operations["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ResearchWorkspaceEnvelope",
        )

    def test_database_url_composes_durable_p5_repositories_without_connecting(self) -> None:
        with patch.dict(
            os.environ,
            {"ASP_DATABASE_URL": "postgresql://research.invalid/p5"},
            clear=True,
        ):
            app = create_app()

        self.assertIsInstance(
            app.state.expected_return_repository,
            PostgresExpectedReturnLedgerRepository,
        )
        self.assertIsInstance(
            app.state.signal_snapshot_repository,
            PostgresSignalSnapshotRepository,
        )


if __name__ == "__main__":
    unittest.main()
