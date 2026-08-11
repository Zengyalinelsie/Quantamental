import unittest
from dataclasses import replace

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
    UnavailableExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.factor_reviews import InMemoryFactorReviewRepository
from a_share_platform.adapters.memory.signals import InMemorySignalSnapshotRepository
from a_share_platform.application.research_workspace import ResearchWorkspaceProjectionService
from a_share_platform.application.signal_snapshots import SignalSnapshotLedgerService
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.security_master import SecurityMaster
from tests.test_signal_snapshot_ledger import snapshot_for
from tests.test_signal_snapshots import approved_factor_package, investment_view


class ResearchWorkspaceProjectionServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.expected_returns = InMemoryExpectedReturnLedgerRepository()
        self.signals = InMemorySignalSnapshotRepository()
        self.reviews = InMemoryFactorReviewRepository()

    def service(self) -> ResearchWorkspaceProjectionService:
        return ResearchWorkspaceProjectionService(
            expected_return_repository=self.expected_returns,
            signal_snapshot_repository=self.signals,
            factor_review_repository=self.reviews,
            security_master=SecurityMaster.empty(),
        )

    def test_empty_runtime_is_professionally_unavailable_without_demo_values(self) -> None:
        value = self.service().project()

        self.assertEqual(value["status"], "unavailable")
        self.assertIsNone(value["screen"])
        self.assertIsNone(value["investment_view"])
        self.assertEqual(value["alpha_model"]["status"], "unavailable")
        blocker_codes = {item["code"] for item in value["blockers"]}
        self.assertEqual(
            blocker_codes,
            {
                "investment_view_unavailable",
                "research_signal_snapshot_unavailable",
                "approved_alpha_model_unavailable",
            },
        )
        self.assertNotIn("demo", str(value).lower())

    def test_unconfigured_durable_store_becomes_evidence_backed_blocker(self) -> None:
        service = ResearchWorkspaceProjectionService(
            expected_return_repository=UnavailableExpectedReturnLedgerRepository(
                "durable Expected Return ledger is not configured"
            ),
            signal_snapshot_repository=self.signals,
            factor_review_repository=self.reviews,
            security_master=SecurityMaster.empty(),
        )

        value = service.project()

        self.assertEqual(value["status"], "unavailable")
        store_blocker = next(
            item
            for item in value["blockers"]
            if item["code"] == "investment_view_store_unavailable"
        )
        self.assertIn("not configured", store_blocker["reason"])

    def test_ready_projection_is_server_ranked_closed_and_version_bound(self) -> None:
        view = investment_view()
        research_snapshot = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        self.expected_returns.append_view(view)
        SignalSnapshotLedgerService(self.signals).record_snapshot(research_snapshot)
        self.reviews.save_review(review)

        value = self.service().project(security_query=view.security_id)

        self.assertEqual(value["status"], "ready")
        self.assertEqual(value["blockers"], [])
        screen = value["screen"]
        self.assertEqual(screen["rows"][0]["rank"]["value"], research_snapshot.rank)
        self.assertEqual(
            screen["rows"][0]["rank_change"]["value"],
            research_snapshot.rank_change,
        )
        self.assertEqual(screen["rows"][0]["expected_return"]["raw"], "0.045")
        self.assertTrue(screen["rows"][0]["selected"])
        projected_view = value["investment_view"]
        self.assertEqual(projected_view["view_id"], view.view_id)
        self.assertEqual(projected_view["closure"]["status"], "passed")
        event = next(item for item in projected_view["components"] if item["component"] == "event")
        self.assertEqual(event["status"], "unavailable")
        self.assertIsNone(event["contribution"])
        self.assertEqual(value["alpha_model"]["status"], "ready")
        self.assertEqual(
            value["alpha_model"]["model"]["environment_id"],
            view.environment_id,
        )
        self.assertIsNone(projected_view["versions"]["artifact_id"])
        self.assertEqual(
            value["alpha_model"]["factors"][0]["approval"]["scope"],
            "research_backtest",
        )

    def test_selected_view_is_the_exact_snapshot_binding_not_a_newer_same_security_view(
        self,
    ) -> None:
        frozen = investment_view()
        newer = replace(
            frozen,
            view_id="investment-view:newer-unbound:v1",
            decision_time=frozen.decision_time.replace(hour=frozen.decision_time.hour + 1),
        )
        snapshot = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        self.expected_returns.append_view(frozen)
        self.expected_returns.append_view(newer)
        SignalSnapshotLedgerService(self.signals).record_snapshot(snapshot)
        self.reviews.save_review(review)

        value = self.service().project(security_query=frozen.security_id)

        self.assertEqual(value["investment_view"]["view_id"], snapshot.investment_view_id)
        self.assertEqual(
            value["investment_view"]["versions"]["content_hash"],
            snapshot.investment_view_hash,
        )

    def test_screen_does_not_mix_incompatible_factor_or_data_mode_bindings(self) -> None:
        current = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        incompatible = replace(
            current,
            snapshot_id="signal-snapshot:zz-incompatible:v1",
            security_id="security:CN:000001:XSHE",
            factor_version_ids=("factor-version:other:v1",),
            factor_version_hashes=("9" * 64,),
            factor_review_ids=("review:other:v1",),
            factor_review_hashes=("8" * 64,),
        )
        SignalSnapshotLedgerService(self.signals).record_snapshot(current)
        SignalSnapshotLedgerService(self.signals).record_snapshot(incompatible)

        value = self.service().project()

        self.assertEqual(len(value["screen"]["rows"]), 1)
        self.assertEqual(
            value["screen"]["factor_version_ids"],
            ["factor-version:other:v1"],
        )

    def test_forward_snapshot_never_leaks_into_research_workspace(self) -> None:
        SignalSnapshotLedgerService(self.signals).record_snapshot(
            snapshot_for(ApprovalScope.SHADOW)
        )

        value = self.service().project()

        self.assertIsNone(value["screen"])
        self.assertEqual(value["alpha_model"]["status"], "unavailable")
        self.assertTrue(
            any(
                item["code"] == "research_signal_snapshot_unavailable" for item in value["blockers"]
            )
        )

    def test_unknown_security_filter_does_not_fall_back_to_another_security(self) -> None:
        self.expected_returns.append_view(investment_view())

        value = self.service().project(security_query="security:unknown")

        self.assertIsNone(value["investment_view"])
        self.assertTrue(
            any(item["code"] == "investment_view_unavailable" for item in value["blockers"])
        )


if __name__ == "__main__":
    unittest.main()
