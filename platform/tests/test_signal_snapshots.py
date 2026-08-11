import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.expected_return import (
    ExpectedReturnCompileRequest,
    ExpectedReturnCompilerV0,
    ExpectedReturnResidual,
    InvestmentHorizon,
)
from a_share_platform.domain.factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorLifecycleEvent,
    FactorLifecycleStatus,
    FactorVersion,
    PromotionApproval,
    ValidationCheck,
    ValidationCheckName,
    ValidationOutcome,
    ValidationReport,
)
from a_share_platform.domain.factor_reviews import FactorPromotionReview
from a_share_platform.domain.investment_view import (
    InvestmentComponent,
    InvestmentComponentStatus,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.signals import (
    SignalSnapshotCompiler,
    SignalSnapshotCompileRequest,
    SignalSnapshotUnavailable,
)

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)
DATASETS = ("dataset:financials:v1", "dataset:prices:v1")
FEATURES = ("feature:quality:v0", "feature:valuation:v0")
MODEL = "expected-return-compiler:v0"


def digest(marker: str) -> str:
    return marker * 64


def validation_checks() -> tuple[ValidationCheck, ...]:
    return tuple(
        ValidationCheck(
            name=name,
            outcome=ValidationOutcome.PASS,
            evidence_hashes=(digest("a"),),
            detail="Frozen validation artifact passed the declared threshold.",
        )
        for name in ValidationCheckName
    )


def approved_factor_package(
    scope: ApprovalScope = ApprovalScope.RESEARCH_BACKTEST,
) -> tuple[FactorVersion, FactorPromotionReview]:
    factor = FactorVersion(
        factor_version_id="factor-version:alpha:v1",
        factor_id="factor:alpha",
        semantic_version="1.0.0",
        definition_hash=digest("b"),
        code_sha="1" * 40,
        dataset_version_ids=DATASETS,
        feature_version_ids=FEATURES,
        model_version_ids=(MODEL,),
        created_by="user:researcher-01",
        created_at=NOW - timedelta(days=2),
    )
    for source, target, offset in (
        (FactorLifecycleStatus.DRAFT, FactorLifecycleStatus.RESEARCH, -36),
        (FactorLifecycleStatus.RESEARCH, FactorLifecycleStatus.SHADOW, -35),
        (FactorLifecycleStatus.SHADOW, FactorLifecycleStatus.CANDIDATE, -34),
    ):
        factor = factor.transition(
            FactorLifecycleEvent(
                event_id=f"event:{source.value}:{target.value}",
                from_status=source,
                to_status=target,
                actor_id="user:researcher-01",
                actor_role="researcher",
                occurred_at=NOW + timedelta(hours=offset),
                reason="Advance after frozen validation evidence review.",
                evidence_hashes=(digest("c"),),
            )
        )
    report = ValidationReport(
        report_id="validation-report:alpha:v1",
        report_version="v1",
        factor_version_id=factor.factor_version_id,
        experiment_run_id="experiment-run:alpha:001",
        dataset_version_ids=DATASETS,
        code_sha=factor.code_sha,
        artifact_hashes=(digest("d"),),
        run_context=RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH),
        input_trust_state=DataTrustState.PIT_VERIFIED,
        checks=validation_checks(),
        created_at=NOW - timedelta(hours=33),
    )
    approval = PromotionApproval(
        approval_id=f"approval:alpha:{scope.value}:v1",
        factor_version_id=factor.factor_version_id,
        validation_report_id=report.report_id,
        validation_report_hash=report.content_hash,
        scope=scope,
        decision=ApprovalDecision.APPROVED,
        actor_id="user:reviewer-01",
        actor_role="reviewer",
        decided_at=NOW - timedelta(hours=32),
        reason="Approved only for the exact declared signal use.",
        evidence_hashes=(digest("e"),),
    )
    review = FactorPromotionReview.from_evidence(
        factor_version=factor,
        validation_report=report,
        approval=approval,
    )
    production = factor.transition(
        FactorLifecycleEvent(
            event_id="event:candidate:production",
            from_status=FactorLifecycleStatus.CANDIDATE,
            to_status=FactorLifecycleStatus.PRODUCTION,
            actor_id="user:reviewer-01",
            actor_role="reviewer",
            occurred_at=NOW - timedelta(hours=31),
            reason="Bind the exact validation report and approval.",
            evidence_hashes=(digest("f"),),
        ),
        validation_report=report,
        approval=approval,
        scope=scope,
    )
    return production, review


def approved_factor(
    scope: ApprovalScope = ApprovalScope.RESEARCH_BACKTEST,
) -> FactorVersion:
    return approved_factor_package(scope)[0]


def investment_view(
    run_context: RunContext | None = None,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
):
    context = run_context or RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH)
    return ExpectedReturnCompilerV0().compile(
        ExpectedReturnCompileRequest(
            security_id="security:CN:600519:XSHG",
            decision_time=NOW,
            horizon=InvestmentHorizon.DAYS_60,
            components=(
                InvestmentComponent(
                    "quality",
                    InvestmentComponentStatus.QUANTIFIED,
                    Decimal("0.018"),
                    ("evidence:quality",),
                ),
                InvestmentComponent(
                    "valuation",
                    InvestmentComponentStatus.QUANTIFIED,
                    Decimal("0.021"),
                    ("evidence:valuation",),
                ),
                InvestmentComponent(
                    "revision",
                    InvestmentComponentStatus.CONSTRAINED,
                    status_reason="revision coverage is current-only",
                ),
                InvestmentComponent(
                    "event",
                    InvestmentComponentStatus.UNAVAILABLE,
                    status_reason="P8 event model is not implemented",
                ),
            ),
            residual=ExpectedReturnResidual(
                Decimal("0.006"),
                "V0 unexplained portion remains explicit.",
                ("artifact:residual-policy:v0",),
            ),
            p10=Decimal("-0.12"),
            p50=Decimal("0.04"),
            p90=Decimal("0.19"),
            downside=Decimal("-0.18"),
            confidence=Decimal("0.62"),
            catalysts=("margin recovery is confirmed",),
            invalidators=("cash flow deteriorates",),
            dataset_version_ids=DATASETS,
            feature_version_ids=FEATURES,
            model_version_id=MODEL,
            run_id="run:p5:signal:001",
            code_version="1" * 40,
            environment_id="environment:p5:test:v1",
            run_context=context,
            trust_state=trust_state,
            latest_input_available_at=NOW - timedelta(minutes=5),
        )
    )


def request(**overrides: object) -> SignalSnapshotCompileRequest:
    factor, review = approved_factor_package()
    values: dict[str, object] = {
        "investment_view": investment_view(),
        "factor_versions": (factor,),
        "factor_reviews": (review,),
        "approval_scope": ApprovalScope.RESEARCH_BACKTEST,
        "universe_version_id": "universe:csi500:2026-08-11:v1",
        "rank": 12,
        "previous_rank": 18,
        "universe_size": 500,
        "score": Decimal("1.274"),
        "created_at": NOW + timedelta(minutes=2),
    }
    values.update(overrides)
    return SignalSnapshotCompileRequest(**values)  # type: ignore[arg-type]


class SignalSnapshotCompilerTest(unittest.TestCase):
    def test_compiles_immutable_ranked_signal_with_exact_lineage(self) -> None:
        snapshot = SignalSnapshotCompiler().compile(request())

        self.assertTrue(snapshot.snapshot_id.startswith("signal-snapshot:"))
        self.assertEqual(snapshot.rank, 12)
        self.assertEqual(snapshot.rank_change, 6)
        self.assertEqual(snapshot.expected_return, Decimal("0.045"))
        self.assertEqual(snapshot.confidence, Decimal("0.62"))
        self.assertEqual(snapshot.investment_view_id, investment_view().view_id)
        self.assertEqual(snapshot.factor_version_ids, ("factor-version:alpha:v1",))
        self.assertEqual(snapshot.approval_scope, ApprovalScope.RESEARCH_BACKTEST)
        self.assertEqual(snapshot.data_cutoff, NOW - timedelta(minutes=5))
        self.assertEqual(len(snapshot.content_hash), 64)

    def test_identifier_is_deterministic_and_decimal_canonical(self) -> None:
        compiler = SignalSnapshotCompiler()
        first = compiler.compile(request())
        second = compiler.compile(request(score=Decimal("1.2740")))
        changed = compiler.compile(request(rank=13))

        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertNotEqual(first.snapshot_id, changed.snapshot_id)

    def test_scope_must_match_run_context_and_exact_factor_approval(self) -> None:
        shadow_view = investment_view(
            RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.SHADOW)
        )
        with self.assertRaisesRegex(SignalSnapshotUnavailable, "not approved"):
            SignalSnapshotCompiler().compile(
                request(
                    investment_view=shadow_view,
                    approval_scope=ApprovalScope.SHADOW,
                )
            )
        with self.assertRaisesRegex(ValueError, "research run context"):
            request(approval_scope=ApprovalScope.SHADOW)

    def test_model_feature_and_dataset_bindings_cannot_escape_approved_factor(self) -> None:
        wrong_model = approved_factor()
        values = wrong_model.__dict__.copy()
        values.pop("content_hash")
        values["model_version_ids"] = ("model:other:v1",)
        with self.assertRaisesRegex(SignalSnapshotUnavailable, "exact FactorVersion"):
            SignalSnapshotCompiler().compile(
                request(factor_versions=(FactorVersion(**values),))
            )

    def test_rank_cutoff_and_previous_rank_are_validated_without_fake_zero_change(self) -> None:
        snapshot = SignalSnapshotCompiler().compile(request(previous_rank=None))
        self.assertIsNone(snapshot.rank_change)
        with self.assertRaisesRegex(ValueError, "rank cannot exceed universe_size"):
            request(rank=501)
        with self.assertRaisesRegex(ValueError, "created_at cannot precede decision_time"):
            request(created_at=NOW - timedelta(minutes=1))

    def test_strict_snapshot_requires_pit_view_and_stays_research_only(self) -> None:
        strict_view = investment_view(
            RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH),
            DataTrustState.PIT_VERIFIED,
        )
        snapshot = SignalSnapshotCompiler().compile(request(investment_view=strict_view))
        self.assertIs(snapshot.trust_state, DataTrustState.PIT_VERIFIED)
        self.assertIs(snapshot.approval_scope, ApprovalScope.RESEARCH_BACKTEST)


if __name__ == "__main__":
    unittest.main()
