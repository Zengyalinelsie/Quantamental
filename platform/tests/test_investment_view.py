import unittest
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.domain.investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext


def quantified_component(
    name: str = "quality",
    contribution: Decimal = Decimal("0.02"),
    evidence_ids: tuple[str, ...] = ("fact:roe",),
) -> InvestmentComponent:
    return InvestmentComponent(
        name=name,
        status=InvestmentComponentStatus.QUANTIFIED,
        expected_return_contribution=contribution,
        evidence_ids=evidence_ids,
    )


def make_view(
    *,
    point: Decimal = Decimal("0.05"),
    components: tuple[InvestmentComponent, ...] | None = None,
    residual: Decimal = Decimal("0.03"),
    invalidators: tuple[str, ...] = ("ROE 下修",),
) -> InvestmentView:
    return InvestmentView(
        view_id="view:001",
        security_id="security:CN:600519:XSHG",
        decision_time=datetime(2026, 8, 10, 7, 30, tzinfo=UTC),
        horizon_trading_days=60,
        expected_return=ExpectedReturnDistribution(
            point,
            Decimal("-0.12"),
            Decimal("0.04"),
            Decimal("0.19"),
            Decimal("-0.18"),
        ),
        confidence=Decimal("0.62"),
        components=components or (quantified_component(),),
        residual=residual,
        residual_reason="V0 未解释部分显式保留",
        residual_evidence_ids=("artifact:residual-policy:v0",),
        catalysts=("后续报告确认经营改善",),
        invalidators=invalidators,
        dataset_version_ids=("dataset:financials:v1", "dataset:prices:v1"),
        feature_version_ids=("feature:quality:v0",),
        model_version_id="expected-return:v1",
        run_id="run:investment-view:001",
        code_version="0123456789abcdef0123456789abcdef01234567",
        environment_id="environment:test:v1",
        run_context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        latest_input_available_at=datetime(2026, 8, 10, 7, 25, tzinfo=UTC),
    )


class InvestmentViewTest(unittest.TestCase):
    def test_view_binds_statuses_distribution_evidence_versions_and_residual(self) -> None:
        view = make_view(
            point=Decimal("0.045"),
            components=(
                quantified_component(
                    "quality", Decimal("0.018"), ("fact:roe", "fact:cashflow")
                ),
                quantified_component(
                    "valuation", Decimal("0.021"), ("fact:market_cap",)
                ),
                InvestmentComponent(
                    "revision",
                    InvestmentComponentStatus.CONSTRAINED,
                    evidence_ids=("estimate:eps",),
                    status_reason="预测覆盖不足，仅降低置信度",
                ),
                InvestmentComponent(
                    "event",
                    InvestmentComponentStatus.UNAVAILABLE,
                    status_reason="事件模型尚未实现",
                ),
            ),
            residual=Decimal("0.006"),
        )
        self.assertEqual(view.component_total, Decimal("0.039"))
        self.assertEqual(view.residual, Decimal("0.006"))
        self.assertEqual(view.reconciled_expected_return, Decimal("0.045"))
        self.assertEqual(len(view.all_evidence_ids), 5)
        self.assertEqual(len(view.content_hash), 64)

    def test_all_component_status_values_match_spec_024(self) -> None:
        self.assertEqual(
            {item.value for item in InvestmentComponentStatus},
            {"quantified", "constrained", "unavailable", "not_applicable"},
        )

    def test_status_string_is_normalized(self) -> None:
        component = InvestmentComponent(
            "event",
            "not_applicable",
            status_reason="策略明确不使用事件暴露",
        )
        self.assertIs(component.status, InvestmentComponentStatus.NOT_APPLICABLE)

    def test_quantified_component_requires_numeric_contribution_and_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires an expected-return contribution"):
            InvestmentComponent("quality", InvestmentComponentStatus.QUANTIFIED)
        with self.assertRaisesRegex(ValueError, "requires at least one evidence"):
            InvestmentComponent(
                "quality",
                InvestmentComponentStatus.QUANTIFIED,
                expected_return_contribution=Decimal("0.02"),
            )

    def test_non_quantified_components_reject_numeric_zero(self) -> None:
        for status in (
            InvestmentComponentStatus.CONSTRAINED,
            InvestmentComponentStatus.UNAVAILABLE,
            InvestmentComponentStatus.NOT_APPLICABLE,
        ):
            with self.subTest(status=status), self.assertRaisesRegex(
                ValueError, "must not have a numeric contribution"
            ):
                InvestmentComponent(
                    "event",
                    status,
                    expected_return_contribution=Decimal(0),
                    status_reason="不能把非量化状态伪装为零",
                )

    def test_non_quantified_components_require_explicit_reason(self) -> None:
        for status in (
            InvestmentComponentStatus.CONSTRAINED,
            InvestmentComponentStatus.UNAVAILABLE,
            InvestmentComponentStatus.NOT_APPLICABLE,
        ):
            with self.subTest(status=status), self.assertRaisesRegex(
                ValueError, "requires an explicit reason"
            ):
                InvestmentComponent("event", status)

    def test_view_rejects_unordered_return_distribution(self) -> None:
        with self.assertRaisesRegex(ValueError, "p10 <= p50 <= p90"):
            ExpectedReturnDistribution(
                Decimal("0.04"),
                Decimal("0.10"),
                Decimal("0.00"),
                Decimal("0.20"),
                Decimal("-0.10"),
            )

    def test_view_requires_explicit_invalidators(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit invalidators"):
            make_view(invalidators=())

    def test_view_requires_quantified_contributions_plus_residual_to_reconcile(self) -> None:
        with self.assertRaisesRegex(ValueError, "plus residual must reconcile"):
            make_view(point=Decimal("0.05"), residual=Decimal("0.02"))

    def test_residual_must_be_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "residual must be finite"):
            make_view(residual=Decimal("NaN"))

    def test_float_is_rejected_for_reproducible_return_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "must be a Decimal"):
            quantified_component(contribution=0.02)  # type: ignore[arg-type]

    def test_strict_historical_rejects_current_trust(self) -> None:
        values = make_view().__dict__
        values.pop("content_hash")
        values["run_context"] = RunContext(
            DataMode.STRICT_HISTORICAL,
            DeploymentStage.RESEARCH,
        )
        with self.assertRaisesRegex(ValueError, "strict_historical requires pit_verified"):
            InvestmentView(**values)


if __name__ == "__main__":
    unittest.main()
