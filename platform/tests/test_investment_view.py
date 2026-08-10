import unittest
from datetime import UTC, datetime

from a_share_platform.domain.investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)


def quantified_component(
    name: str = "quality",
    contribution: float = 0.02,
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
    point: float = 0.05,
    components: tuple[InvestmentComponent, ...] | None = None,
    residual: float = 0.03,
    invalidators: tuple[str, ...] = ("ROE 下修",),
) -> InvestmentView:
    return InvestmentView(
        view_id="view:001",
        security_id="security:CN:600519:XSHG",
        decision_time=datetime(2026, 8, 10, 7, 30, tzinfo=UTC),
        horizon_trading_days=60,
        expected_return=ExpectedReturnDistribution(point, -0.12, 0.04, 0.19),
        confidence=0.62,
        components=components or (quantified_component(),),
        residual=residual,
        invalidators=invalidators,
        dataset_version_ids=("dataset:financials:v1", "dataset:prices:v1"),
        model_version_id="expected-return:v1",
    )


class InvestmentViewTest(unittest.TestCase):
    def test_view_binds_statuses_distribution_evidence_versions_and_residual(self) -> None:
        view = make_view(
            point=0.045,
            components=(
                quantified_component("quality", 0.018, ("fact:roe", "fact:cashflow")),
                quantified_component("valuation", 0.021, ("fact:market_cap",)),
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
            residual=0.006,
        )
        self.assertAlmostEqual(view.component_total, 0.039)
        self.assertAlmostEqual(view.residual, 0.006)
        self.assertAlmostEqual(view.reconciled_expected_return, 0.045)
        self.assertEqual(len(view.all_evidence_ids), 4)

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
                expected_return_contribution=0.02,
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
                    expected_return_contribution=0.0,
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
            ExpectedReturnDistribution(0.04, 0.10, 0.00, 0.20)

    def test_view_requires_explicit_invalidators(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit invalidators"):
            make_view(invalidators=())

    def test_view_requires_quantified_contributions_plus_residual_to_reconcile(self) -> None:
        with self.assertRaisesRegex(ValueError, "plus residual must reconcile"):
            make_view(point=0.05, residual=0.02)

    def test_residual_must_be_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "residual must be finite"):
            make_view(residual=float("nan"))


if __name__ == "__main__":
    unittest.main()
