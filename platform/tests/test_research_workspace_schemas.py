import unittest
from copy import deepcopy
from datetime import UTC, datetime

from pydantic import ValidationError

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.factor_reviews import (
    InMemoryFactorReviewRepository,
)
from a_share_platform.adapters.memory.signals import InMemorySignalSnapshotRepository
from a_share_platform.api.schemas import (
    AlphaModelReadyProjection,
    AlphaModelUnavailableProjection,
    ResearchWorkspaceData,
    ResearchWorkspaceEnvelope,
)
from a_share_platform.application.research_workspace import (
    ResearchWorkspaceProjectionService,
)
from a_share_platform.application.signal_snapshots import SignalSnapshotLedgerService
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.security_master import SecurityMaster
from tests.test_signal_snapshot_ledger import snapshot_for
from tests.test_signal_snapshots import approved_factor_package, investment_view


class ResearchWorkspaceSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self.expected_returns = InMemoryExpectedReturnLedgerRepository()
        self.signals = InMemorySignalSnapshotRepository()
        self.reviews = InMemoryFactorReviewRepository()
        self.service = ResearchWorkspaceProjectionService(
            expected_return_repository=self.expected_returns,
            signal_snapshot_repository=self.signals,
            factor_review_repository=self.reviews,
            security_master=SecurityMaster.empty(),
        )

    @staticmethod
    def context() -> dict[str, object]:
        now = datetime(2026, 8, 11, 9, 30, tzinfo=UTC)
        return {
            "as_of": now,
            "system_as_of": now,
            "data_mode": "current_research",
            "deployment_stage": "research",
            "trust_state": "normalized_current",
            "dataset_version_ids": ["dataset:research:v1"],
            "model_version_ids": ["model:research:v1"],
            "run_id": "run:research:v1",
            "coverage": {"screen_rows": 1, "selected_security": True},
            "warnings": [],
        }

    def ready_payload(self) -> dict[str, object]:
        view = investment_view()
        snapshot = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        self.expected_returns.append_view(view)
        SignalSnapshotLedgerService(self.signals).record_snapshot(snapshot)
        self.reviews.save_review(review)
        return self.service.project(security_query=view.security_id)

    def test_real_unavailable_projection_validates_without_demo_values(self) -> None:
        payload = self.service.project()

        value = ResearchWorkspaceData.model_validate(payload)

        self.assertEqual(value.status, "unavailable")
        self.assertIsNone(value.screen)
        self.assertIsNone(value.investment_view)
        self.assertIsInstance(value.alpha_model, AlphaModelUnavailableProjection)
        assert isinstance(value.alpha_model, AlphaModelUnavailableProjection)
        self.assertGreaterEqual(len(value.alpha_model.blocked_reasons), 1)

    def test_real_ready_projection_and_envelope_preserve_frozen_bindings(self) -> None:
        payload = self.ready_payload()

        data = ResearchWorkspaceData.model_validate(payload)
        envelope = ResearchWorkspaceEnvelope.model_validate(
            {"data": payload, "context": self.context()}
        )

        self.assertEqual(data.status, "ready")
        self.assertIsInstance(data.alpha_model, AlphaModelReadyProjection)
        assert isinstance(data.alpha_model, AlphaModelReadyProjection)
        self.assertTrue(data.alpha_model.factors[0].scientific_gate_passed)
        self.assertEqual(data.alpha_model.factors[0].approval.decision, "approved")
        self.assertIsNotNone(data.screen)
        self.assertIsNotNone(data.investment_view)
        assert data.screen is not None
        assert data.investment_view is not None
        self.assertEqual(
            data.screen.rows[0].content_hash,
            payload["screen"]["rows"][0]["content_hash"],  # type: ignore[index]
        )
        self.assertEqual(
            data.alpha_model.model.investment_view_hash,
            data.investment_view.versions.content_hash,
        )
        self.assertIsNone(data.investment_view.versions.artifact_id)
        self.assertEqual(envelope.data.status, "ready")
        self.assertEqual(envelope.context.coverage["screen_rows"], 1)

    def test_artifact_id_accepts_none_or_real_immutable_artifact_id(self) -> None:
        payload = self.ready_payload()
        versions = payload["investment_view"]["versions"]  # type: ignore[index]
        self.assertIsNone(versions["artifact_id"])
        ResearchWorkspaceData.model_validate(payload)

        versions["artifact_id"] = "artifact:investment-view:v1"
        value = ResearchWorkspaceData.model_validate(payload)

        assert value.investment_view is not None
        self.assertEqual(
            value.investment_view.versions.artifact_id,
            "artifact:investment-view:v1",
        )

    def test_top_level_and_deep_unknown_fields_are_rejected(self) -> None:
        payload = self.ready_payload()
        top_level = deepcopy(payload)
        top_level["runtime_demo"] = True
        deep = deepcopy(payload)
        deep["screen"]["rows"][0]["client_rank"] = 999  # type: ignore[index]

        with self.assertRaises(ValidationError):
            ResearchWorkspaceData.model_validate(top_level)
        with self.assertRaises(ValidationError):
            ResearchWorkspaceData.model_validate(deep)

    def test_alpha_ready_literals_fail_closed(self) -> None:
        payload = self.ready_payload()
        factor = payload["alpha_model"]["factors"][0]  # type: ignore[index]
        factor["scientific_gate_passed"] = False

        with self.assertRaises(ValidationError):
            ResearchWorkspaceData.model_validate(payload)

        payload = self.ready_payload()
        approval = payload["alpha_model"]["factors"][0]["approval"]  # type: ignore[index]
        approval["reviewer_role"] = "agent"
        with self.assertRaises(ValidationError):
            ResearchWorkspaceData.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
