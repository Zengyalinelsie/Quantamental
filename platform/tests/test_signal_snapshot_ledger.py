import unittest
from dataclasses import replace

from a_share_platform.adapters.memory.signals import (
    InMemorySignalSnapshotRepository,
    UnavailableSignalSnapshotRepository,
)
from a_share_platform.application.signal_snapshots import (
    ProductionSignalSnapshotQueryService,
    ResearchSignalSnapshotQueryService,
    SignalSnapshotLedgerService,
    SignalSnapshotQuerySurfaceDenied,
)
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.signals import SignalSnapshot, SignalSnapshotCompiler
from a_share_platform.ports.signals import (
    SignalSnapshotLedgerConflict,
    SignalSnapshotLedgerUnavailable,
)
from tests.test_signal_snapshots import approved_factor_package, investment_view, request


def snapshot_for(scope: ApprovalScope) -> SignalSnapshot:
    stage = {
        ApprovalScope.RESEARCH_BACKTEST: DeploymentStage.RESEARCH,
        ApprovalScope.SHADOW: DeploymentStage.SHADOW,
        ApprovalScope.PAPER: DeploymentStage.PAPER,
        ApprovalScope.LIMITED_LIVE: DeploymentStage.LIMITED_LIVE,
    }[scope]
    factor, review = approved_factor_package(scope)
    return SignalSnapshotCompiler().compile(
        request(
            investment_view=investment_view(
                RunContext(DataMode.CURRENT_RESEARCH, stage)
            ),
            factor_versions=(factor,),
            factor_reviews=(review,),
            approval_scope=scope,
        )
    )


class SignalSnapshotLedgerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemorySignalSnapshotRepository()
        self.ledger = SignalSnapshotLedgerService(self.repository)
        self.research = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)

    def test_same_snapshot_id_and_hash_is_idempotent_but_content_conflict_fails(self) -> None:
        first = self.ledger.record_snapshot(self.research)
        second = self.ledger.record_snapshot(self.research)

        self.assertIs(first, second)
        self.assertEqual(self.ledger.get_snapshot(self.research.snapshot_id), self.research)

        changed = replace(self.research, rank=13)
        with self.assertRaisesRegex(SignalSnapshotLedgerConflict, "snapshot_id"):
            self.ledger.record_snapshot(changed)

    def test_natural_key_cannot_be_rewritten_by_changing_snapshot_id(self) -> None:
        self.ledger.record_snapshot(self.research)
        rewritten = replace(
            self.research,
            snapshot_id="signal-snapshot:alternate-id",
            rank=13,
        )

        with self.assertRaisesRegex(SignalSnapshotLedgerConflict, "natural key"):
            self.ledger.record_snapshot(rewritten)

    def test_research_query_surface_only_exposes_research_backtest(self) -> None:
        shadow = snapshot_for(ApprovalScope.SHADOW)
        self.ledger.record_snapshot(self.research)
        self.ledger.record_snapshot(shadow)
        query = ResearchSignalSnapshotQueryService(self.repository)

        self.assertEqual(query.list_snapshots(), (self.research,))
        self.assertEqual(query.get_snapshot(self.research.snapshot_id), self.research)
        with self.assertRaisesRegex(SignalSnapshotQuerySurfaceDenied, "research"):
            query.get_snapshot(shadow.snapshot_id)

    def test_production_query_surface_is_bound_to_one_exact_forward_scope(self) -> None:
        shadow = snapshot_for(ApprovalScope.SHADOW)
        paper = snapshot_for(ApprovalScope.PAPER)
        self.ledger.record_snapshot(self.research)
        self.ledger.record_snapshot(shadow)
        self.ledger.record_snapshot(paper)
        query = ProductionSignalSnapshotQueryService(
            self.repository,
            ApprovalScope.SHADOW,
        )

        self.assertEqual(query.list_snapshots(), (shadow,))
        self.assertEqual(query.get_snapshot(shadow.snapshot_id), shadow)
        for hidden in (self.research, paper):
            with self.subTest(scope=hidden.approval_scope), self.assertRaisesRegex(
                SignalSnapshotQuerySurfaceDenied,
                "production",
            ):
                query.get_snapshot(hidden.snapshot_id)

        with self.assertRaisesRegex(ValueError, "production.*scope"):
            ProductionSignalSnapshotQueryService(
                self.repository,
                ApprovalScope.RESEARCH_BACKTEST,
            )


class UnavailableSignalSnapshotRepositoryTest(unittest.TestCase):
    def test_unconfigured_store_fails_closed_without_runtime_snapshots(self) -> None:
        repository = UnavailableSignalSnapshotRepository(
            "durable SignalSnapshot store is not configured"
        )
        ledger = SignalSnapshotLedgerService(repository)
        query = ResearchSignalSnapshotQueryService(repository)

        with self.assertRaisesRegex(SignalSnapshotLedgerUnavailable, "not configured"):
            ledger.record_snapshot(snapshot_for(ApprovalScope.RESEARCH_BACKTEST))
        with self.assertRaisesRegex(SignalSnapshotLedgerUnavailable, "not configured"):
            query.list_snapshots()


if __name__ == "__main__":
    unittest.main()
