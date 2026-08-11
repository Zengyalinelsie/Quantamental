import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    ExpectedReturnCompileRequest,
    ExpectedReturnCompilerV0,
    ExpectedReturnResidual,
    ExpectedReturnUnavailable,
    InvestmentHorizon,
    InvestmentViewOutcome,
)
from a_share_platform.domain.investment_view import (
    InvestmentComponent,
    InvestmentComponentStatus,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

DECISION_TIME = datetime(2026, 8, 11, 7, 0, tzinfo=UTC)


def component(
    name: str,
    status: InvestmentComponentStatus,
    contribution: Decimal | None = None,
    reason: str | None = None,
) -> InvestmentComponent:
    evidence = (f"evidence:{name}",) if status in {
        InvestmentComponentStatus.QUANTIFIED,
        InvestmentComponentStatus.CONSTRAINED,
    } else ()
    return InvestmentComponent(
        name=name,
        status=status,
        expected_return_contribution=contribution,
        evidence_ids=evidence,
        status_reason=reason,
    )


def request(
    *,
    horizon: InvestmentHorizon = InvestmentHorizon.DAYS_60,
    components: tuple[InvestmentComponent, ...] | None = None,
    run_context: RunContext | None = None,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
) -> ExpectedReturnCompileRequest:
    return ExpectedReturnCompileRequest(
        security_id="security:CN:600519:XSHG",
        decision_time=DECISION_TIME,
        horizon=horizon,
        components=components
        or (
            component("quality", InvestmentComponentStatus.QUANTIFIED, Decimal("0.018")),
            component("valuation", InvestmentComponentStatus.QUANTIFIED, Decimal("0.021")),
            component(
                "revision",
                InvestmentComponentStatus.CONSTRAINED,
                reason="改善输入只达到 current research 资格",
            ),
            component(
                "event",
                InvestmentComponentStatus.UNAVAILABLE,
                reason="P8 事件模型尚未实现",
            ),
        ),
        residual=ExpectedReturnResidual(
            value=Decimal("0.006"),
            reason="V0 未解释部分单列，不分摊给已有分项",
            evidence_ids=("artifact:compiler-residual-policy:v0",),
        ),
        p10=Decimal("-0.12"),
        p50=Decimal("0.04"),
        p90=Decimal("0.19"),
        downside=Decimal("-0.18"),
        confidence=Decimal("0.62"),
        catalysts=("毛利率修复得到后续财报确认",),
        invalidators=("ROE 或经营现金流显著下修",),
        dataset_version_ids=("dataset:financials:v1", "dataset:prices:v1"),
        feature_version_ids=("feature:quality:v0", "feature:valuation:v0"),
        model_version_id="expected-return-compiler:v0",
        run_id="run:p5:compiler:001",
        code_version="0123456789abcdef0123456789abcdef01234567",
        environment_id="environment:p5:test:v1",
        run_context=run_context
        or RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        trust_state=trust_state,
        latest_input_available_at=DECISION_TIME - timedelta(minutes=5),
    )


class ExpectedReturnCompilerV0Test(unittest.TestCase):
    def test_compiles_four_components_with_explicit_residual_downside_and_lineage(self) -> None:
        view = ExpectedReturnCompilerV0().compile(request())

        self.assertTrue(view.view_id.startswith("investment-view:"))
        self.assertEqual(view.expected_return.point, Decimal("0.045"))
        self.assertEqual(view.expected_return.downside, Decimal("-0.18"))
        self.assertEqual(view.component_total, Decimal("0.039"))
        self.assertEqual(view.residual, Decimal("0.006"))
        self.assertEqual(
            view.residual_evidence_ids,
            ("artifact:compiler-residual-policy:v0",),
        )
        self.assertEqual(view.horizon_trading_days, 60)
        self.assertEqual(view.catalysts, ("毛利率修复得到后续财报确认",))
        self.assertEqual(view.run_id, "run:p5:compiler:001")
        self.assertEqual(view.run_context.data_mode, DataMode.CURRENT_RESEARCH)
        self.assertEqual(view.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertIn("artifact:compiler-residual-policy:v0", view.all_evidence_ids)

    def test_identifier_is_deterministic_and_changes_with_frozen_input(self) -> None:
        compiler = ExpectedReturnCompilerV0()
        first = compiler.compile(request())
        second = compiler.compile(request())
        changed = compiler.compile(request(horizon=InvestmentHorizon.DAYS_120))

        self.assertEqual(first.view_id, second.view_id)
        self.assertNotEqual(first.view_id, changed.view_id)

    def test_equivalent_decimal_representations_share_one_identifier(self) -> None:
        compiler = ExpectedReturnCompilerV0()
        first = compiler.compile(request())
        equivalent = (
            component(
                "quality",
                InvestmentComponentStatus.QUANTIFIED,
                Decimal("0.0180"),
            ),
            *request().components[1:],
        )

        self.assertEqual(first.view_id, compiler.compile(request(components=equivalent)).view_id)

    def test_only_20_60_120_day_horizons_are_supported(self) -> None:
        self.assertEqual(
            {item.value for item in InvestmentHorizon},
            {20, 60, 120},
        )
        with self.assertRaisesRegex(ValueError, "20, 60, or 120"):
            ExpectedReturnCompileRequest(**{**request().__dict__, "horizon": 5})

    def test_v0_requires_exact_core_components_and_event_is_unavailable_before_p8(self) -> None:
        missing_event = request().components[:-1]
        with self.assertRaisesRegex(ValueError, "quality, valuation, revision, event"):
            request(components=missing_event)

        quantified_event = (
            *request().components[:-1],
            component("event", InvestmentComponentStatus.QUANTIFIED, Decimal("0.01")),
        )
        with self.assertRaisesRegex(ValueError, "event must remain unavailable"):
            ExpectedReturnCompilerV0().compile(request(components=quantified_event))

    def test_no_quantified_input_fails_instead_of_manufacturing_a_residual_signal(self) -> None:
        unavailable = tuple(
            component(
                name,
                InvestmentComponentStatus.UNAVAILABLE,
                reason=f"{name} 输入不可用",
            )
            for name in ("quality", "valuation", "revision", "event")
        )
        with self.assertRaisesRegex(ExpectedReturnUnavailable, "no quantified component"):
            ExpectedReturnCompilerV0().compile(request(components=unavailable))

    def test_strict_historical_requires_pit_verified_input(self) -> None:
        strict = RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH)
        with self.assertRaisesRegex(ValueError, "strict_historical requires pit_verified"):
            request(run_context=strict, trust_state=DataTrustState.NORMALIZED_CURRENT)

    def test_non_quantified_zero_and_unproven_event_remain_forbidden(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not have a numeric contribution"):
            component(
                "event",
                InvestmentComponentStatus.UNAVAILABLE,
                contribution=Decimal(0),
                reason="不能用零冒充事件无影响",
            )


class ExpectedReturnOutcomeLedgerTest(unittest.TestCase):
    def test_outcome_and_calibration_are_immutable_content_addressed_records(self) -> None:
        view = ExpectedReturnCompilerV0().compile(request())
        outcome = InvestmentViewOutcome(
            outcome_id="outcome:view:001",
            view_id=view.view_id,
            security_id=view.security_id,
            decision_time=view.decision_time,
            horizon_trading_days=view.horizon_trading_days,
            realized_at=DECISION_TIME + timedelta(days=100),
            realized_return=Decimal("-0.03"),
            dataset_version_id="dataset:realized-return:v1",
            recorded_at=DECISION_TIME + timedelta(days=101),
        )
        calibration = ExpectedReturnCalibrationRecord.from_view_and_outcome(
            calibration_id="calibration:view:001",
            view=view,
            outcome=outcome,
            recorded_at=DECISION_TIME + timedelta(days=101),
        )

        self.assertEqual(len(outcome.content_hash), 64)
        self.assertEqual(len(calibration.content_hash), 64)
        self.assertEqual(calibration.absolute_error, Decimal("0.075"))
        self.assertTrue(calibration.inside_p10_p90)
        self.assertFalse(calibration.direction_correct)

    def test_outcome_cannot_be_recorded_before_it_is_realized(self) -> None:
        with self.assertRaisesRegex(ValueError, "recorded_at cannot precede realized_at"):
            InvestmentViewOutcome(
                outcome_id="outcome:invalid",
                view_id="investment-view:invalid",
                security_id="security:CN:600519:XSHG",
                decision_time=DECISION_TIME,
                horizon_trading_days=60,
                realized_at=DECISION_TIME + timedelta(days=100),
                realized_return=Decimal("0.01"),
                dataset_version_id="dataset:realized-return:v1",
                recorded_at=DECISION_TIME + timedelta(days=99),
            )


if __name__ == "__main__":
    unittest.main()
