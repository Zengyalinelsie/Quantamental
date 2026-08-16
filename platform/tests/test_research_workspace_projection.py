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


class ScreenComponentColumnTest(unittest.TestCase):
    """PUI-02 needs per-row quality / valuation / improvement contributions.

    The Figma ranking table (node 3:726) carries 质量 / 估值预期差 / 改善 and a
    60-day expected-return range.  Those are not new data: they already live on
    the frozen InvestmentView the snapshot is bound to, so projecting them keeps
    one source of truth and stays fully traceable.
    """

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

    def ready_row(self) -> dict:
        view = investment_view()
        snapshot = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        _factor, review = approved_factor_package(ApprovalScope.RESEARCH_BACKTEST)
        self.expected_returns.append_view(view)
        SignalSnapshotLedgerService(self.signals).record_snapshot(snapshot)
        self.reviews.save_review(review)
        value = self.service().project(security_query=view.security_id)
        return value["screen"]["rows"][0]

    def test_row_carries_the_frozen_view_component_contributions(self) -> None:
        row = self.ready_row()

        self.assertIn("components", row)
        names = {item["component"] for item in row["components"]}
        self.assertEqual(names, {"quality", "valuation", "revision", "event"})

    def test_each_component_reports_status_and_never_fills_unavailable_with_zero(self) -> None:
        row = self.ready_row()

        for item in row["components"]:
            self.assertIn(
                item["status"],
                ("quantified", "constrained", "unavailable", "not_applicable"),
            )
            if item["status"] == "quantified":
                self.assertIsNotNone(item["contribution"])
                self.assertNotEqual(item["display"], "—")
            else:
                # constrained, unavailable and not_applicable all show an em dash.
                # A constrained component is bounded but not quantified, so it has
                # no contribution either; none of them may be filled with a zero.
                self.assertIsNone(item["contribution"])
                self.assertEqual(item["display"], "—")

    def test_constrained_and_unavailable_are_distinguishable(self) -> None:
        """Both show an em dash, but the status must stay distinct for audit."""
        statuses = {item["component"]: item["status"] for item in self.ready_row()["components"]}

        self.assertEqual(statuses["revision"], "constrained")
        self.assertEqual(statuses["event"], "unavailable")

    def test_row_carries_the_horizon_expected_return_interval(self) -> None:
        row = self.ready_row()

        interval = row["expected_return_interval"]
        self.assertEqual(interval["horizon_trading_days"], 60)
        # Either a real interval from the frozen view, or an explicit absence.
        if interval["display"] is None:
            self.assertIsNotNone(interval["unavailable_reason"])
        else:
            self.assertIsNotNone(interval["lower"])
            self.assertIsNotNone(interval["upper"])

    def test_component_contributions_are_not_recomputed_from_score(self) -> None:
        """The projection reads the frozen view; it does not derive components."""
        row = self.ready_row()

        quantified = [
            item for item in row["components"] if item["status"] == "quantified"
        ]
        self.assertTrue(quantified, "the frozen view has at least one quantified component")
        for item in quantified:
            self.assertIn("evidence_ids", item)

    def test_no_design_fixture_weights_appear_in_the_projection(self) -> None:
        row = self.ready_row()
        rendered = repr(row)

        # Figma builder sample weights and coverage must never reach the runtime.
        for fixture in ("40%", "30%", "96.3", "5000"):
            self.assertNotIn(fixture, rendered)


if __name__ == "__main__":
    unittest.main()
