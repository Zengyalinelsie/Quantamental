from datetime import datetime, timezone
import unittest

from a_share_platform.domain.investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentView,
)


class InvestmentViewTest(unittest.TestCase):
    def test_view_binds_distribution_evidence_and_versions(self) -> None:
        view = InvestmentView(
            view_id="view:001",
            security_id="security:CN:600519:XSHG",
            decision_time=datetime(2026, 8, 10, 7, 30, tzinfo=timezone.utc),
            horizon_trading_days=60,
            expected_return=ExpectedReturnDistribution(0.045, -0.12, 0.04, 0.19),
            confidence=0.62,
            components=(
                InvestmentComponent("quality", 0.018, ("fact:roe", "fact:cashflow")),
                InvestmentComponent("valuation", 0.021, ("fact:market_cap",)),
                InvestmentComponent("revision", 0.012, ("estimate:eps",)),
                InvestmentComponent("event", -0.006, ("event:customer_loss",)),
            ),
            invalidators=("毛利率跌破行业阈值", "核心客户流失"),
            dataset_version_ids=("dataset:financials:v1", "dataset:prices:v1"),
            model_version_id="expected-return:v1",
        )
        self.assertAlmostEqual(view.component_total, 0.045)
        self.assertEqual(len(view.all_evidence_ids), 5)

    def test_view_rejects_unordered_return_distribution(self) -> None:
        with self.assertRaisesRegex(ValueError, "p10 <= p50 <= p90"):
            ExpectedReturnDistribution(0.04, 0.10, 0.00, 0.20)

    def test_view_requires_explicit_invalidators(self) -> None:
        with self.assertRaisesRegex(ValueError, "explicit invalidators"):
            InvestmentView(
                view_id="view:001",
                security_id="security:CN:600519:XSHG",
                decision_time=datetime.now(timezone.utc),
                horizon_trading_days=20,
                expected_return=ExpectedReturnDistribution(0.02, -0.05, 0.02, 0.10),
                confidence=0.5,
                components=(InvestmentComponent("quality", 0.02, ("fact:roe",)),),
                invalidators=(),
                dataset_version_ids=("dataset:v1",),
                model_version_id="model:v1",
            )

    def test_view_requires_component_reconciliation(self) -> None:
        with self.assertRaisesRegex(ValueError, "reconcile"):
            InvestmentView(
                view_id="view:001",
                security_id="security:CN:600519:XSHG",
                decision_time=datetime.now(timezone.utc),
                horizon_trading_days=20,
                expected_return=ExpectedReturnDistribution(0.05, -0.05, 0.02, 0.10),
                confidence=0.5,
                components=(InvestmentComponent("quality", 0.02, ("fact:roe",)),),
                invalidators=("ROE 下修",),
                dataset_version_ids=("dataset:v1",),
                model_version_id="model:v1",
            )


if __name__ == "__main__":
    unittest.main()
