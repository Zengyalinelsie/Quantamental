import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.fundamental_improvement import (
    BaseEffectTreatment,
    FundamentalImprovementExposures,
    FundamentalImprovementInput,
    FundamentalImprovementInputCompilerV0,
    FundamentalImprovementMetric,
    FundamentalImprovementObservationInput,
    ImprovementComparison,
    ImprovementInputProvenance,
    ImprovementResultStatus,
    ImprovementScientificStatus,
    ImprovementWindow,
    OneOffTreatment,
    SeasonalityTreatment,
    fundamental_improvement_definition_v0,
)
from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

HASH_A = "sha256:" + "a" * 64


def provenance(metric: FundamentalImprovementMetric) -> ImprovementInputProvenance:
    return ImprovementInputProvenance(
        dataset_version_id="dataset:financial:2024q4:v3",
        source_version_id="source-version:financial:2024q4:v3",
        mapping_version_id="mapping:canonical-financial:v2",
        metric_definition_id=f"metric:{metric.value}",
        metric_definition_version="v2",
        source_fact_ids=(f"fact:{metric.value}:2024q4:v3",),
        content_hashes=(HASH_A,),
    )


def component_input(
    metric: FundamentalImprovementMetric,
    *,
    level: str | None,
    current_change: str | None,
    prior_change: str | None,
    comparison: ImprovementComparison = ImprovementComparison.YOY,
    window: ImprovementWindow = ImprovementWindow.TTM,
    seasonality: SeasonalityTreatment = SeasonalityTreatment.NOT_APPLICABLE,
    base_effect: BaseEffectTreatment = BaseEffectTreatment.ABSENT,
    one_off: OneOffTreatment = OneOffTreatment.EXCLUDED,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    unavailable_reasons: tuple[str, ...] = (),
    decision_time: datetime | None = None,
    latest_source_available_at: datetime | None = None,
) -> FundamentalImprovementInput:
    if comparison is ImprovementComparison.YOY:
        current_comparison = date(2023, 12, 31)
        prior_comparison = date(2023, 9, 30)
    else:
        current_comparison = date(2024, 9, 30)
        prior_comparison = date(2024, 6, 30)
    level_unit = (
        MetricUnit.RATIO if metric is FundamentalImprovementMetric.MARGIN else MetricUnit.CURRENCY
    )
    return FundamentalImprovementInput(
        metric=metric,
        level=None if level is None else Decimal(level),
        current_change=None if current_change is None else Decimal(current_change),
        prior_change=None if prior_change is None else Decimal(prior_change),
        level_unit=level_unit,
        change_unit=MetricUnit.RATIO,
        currency=None if level_unit is MetricUnit.RATIO else "CNY",
        comparison=comparison,
        window=window,
        current_period_end=date(2024, 12, 31),
        current_comparison_period_end=current_comparison,
        prior_period_end=date(2024, 9, 30),
        prior_comparison_period_end=prior_comparison,
        seasonality_treatment=seasonality,
        base_effect_treatment=base_effect,
        one_off_treatment=one_off,
        provenance=provenance(metric),
        data_mode=data_mode,
        trust_state=trust_state,
        unavailable_reasons=unavailable_reasons,
        decision_time=decision_time,
        latest_source_available_at=latest_source_available_at,
    )


def exposures(
    *,
    industry: str | None = "C30",
    size: str | None = "23.5",
    beta: str | None = "1.1",
) -> FundamentalImprovementExposures:
    return FundamentalImprovementExposures(
        industry_code=industry,
        log_market_cap=None if size is None else Decimal(size),
        beta=None if beta is None else Decimal(beta),
    )


class FundamentalImprovementV0HandCalculationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = fundamental_improvement_definition_v0()

    def test_four_metric_yoy_ttm_level_trend_acceleration_and_breadth(self) -> None:
        values = {
            FundamentalImprovementMetric.REVENUE: component_input(
                FundamentalImprovementMetric.REVENUE,
                level="120",
                current_change="0.20",
                prior_change="0.10",
            ),
            FundamentalImprovementMetric.PROFIT: component_input(
                FundamentalImprovementMetric.PROFIT,
                level="30",
                current_change="0.50",
                prior_change="0.20",
            ),
            FundamentalImprovementMetric.MARGIN: component_input(
                FundamentalImprovementMetric.MARGIN,
                level="0.25",
                current_change="0.02",
                prior_change="0.01",
            ),
            FundamentalImprovementMetric.CASH_FLOW: component_input(
                FundamentalImprovementMetric.CASH_FLOW,
                level="25",
                current_change="-0.10",
                prior_change="-0.20",
            ),
        }

        result = self.definition.calculate(
            values,
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(result.status, ImprovementResultStatus.QUANTIFIED)
        self.assertEqual(result.breadth, Decimal(1))
        self.assertEqual(result.confidence, Decimal(1))
        revenue = result.component(FundamentalImprovementMetric.REVENUE)
        self.assertEqual(revenue.level, Decimal(120))
        self.assertEqual(revenue.trend, Decimal("0.20"))
        self.assertEqual(revenue.acceleration, Decimal("0.10"))
        margin = result.component(FundamentalImprovementMetric.MARGIN)
        self.assertEqual(margin.level_unit, MetricUnit.RATIO)
        self.assertEqual(margin.acceleration, Decimal("0.01"))

    def test_mixed_acceleration_breadth_counts_only_strict_improvement(self) -> None:
        changes = {
            FundamentalImprovementMetric.REVENUE: ("0.10", "0.20"),
            FundamentalImprovementMetric.PROFIT: ("0.20", "0.20"),
            FundamentalImprovementMetric.MARGIN: ("0.03", "0.01"),
            FundamentalImprovementMetric.CASH_FLOW: ("-0.10", "0.10"),
        }
        values = {
            metric: component_input(
                metric,
                level="1",
                current_change=current,
                prior_change=prior,
            )
            for metric, (current, prior) in changes.items()
        }

        result = self.definition.calculate(
            values,
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(result.breadth, Decimal("0.25"))
        self.assertEqual(result.confidence, Decimal(1))
        self.assertEqual(
            result.component(FundamentalImprovementMetric.PROFIT).acceleration,
            Decimal(0),
        )


class FundamentalImprovementInputCompilerV0Test(unittest.TestCase):
    def observation(
        self,
        metric: FundamentalImprovementMetric,
        *,
        current: str,
        current_comparison: str,
        prior: str,
        prior_comparison: str,
        current_one_off: str = "0",
        current_comparison_one_off: str = "0",
        prior_one_off: str = "0",
        prior_comparison_one_off: str = "0",
        comparison: ImprovementComparison = ImprovementComparison.YOY,
        window: ImprovementWindow = ImprovementWindow.TTM,
        seasonality: SeasonalityTreatment = SeasonalityTreatment.NOT_APPLICABLE,
        base_effect: BaseEffectTreatment = BaseEffectTreatment.ABSENT,
        one_off: OneOffTreatment = OneOffTreatment.EXCLUDED,
    ) -> FundamentalImprovementObservationInput:
        if comparison is ImprovementComparison.YOY:
            current_comparison_period = date(2023, 12, 31)
            prior_comparison_period = date(2023, 9, 30)
        else:
            current_comparison_period = date(2024, 9, 30)
            prior_comparison_period = date(2024, 6, 30)
        return FundamentalImprovementObservationInput(
            metric=metric,
            current_reported=Decimal(current),
            current_comparison_reported=Decimal(current_comparison),
            prior_reported=Decimal(prior),
            prior_comparison_reported=Decimal(prior_comparison),
            current_one_off=Decimal(current_one_off),
            current_comparison_one_off=Decimal(current_comparison_one_off),
            prior_one_off=Decimal(prior_one_off),
            prior_comparison_one_off=Decimal(prior_comparison_one_off),
            level_unit=(
                MetricUnit.RATIO
                if metric is FundamentalImprovementMetric.MARGIN
                else MetricUnit.CURRENCY
            ),
            currency=(None if metric is FundamentalImprovementMetric.MARGIN else "CNY"),
            comparison=comparison,
            window=window,
            current_period_end=date(2024, 12, 31),
            current_comparison_period_end=current_comparison_period,
            prior_period_end=date(2024, 9, 30),
            prior_comparison_period_end=prior_comparison_period,
            seasonality_treatment=seasonality,
            base_effect_treatment=base_effect,
            one_off_treatment=one_off,
            provenance=provenance(metric),
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            decision_time=datetime(2025, 1, 2, 15, 0, tzinfo=UTC),
            latest_source_available_at=datetime(2025, 1, 2, 14, 59, tzinfo=UTC),
        )

    def test_compiles_one_off_adjusted_level_trend_and_acceleration(self) -> None:
        compiled = FundamentalImprovementInputCompilerV0().compile(
            self.observation(
                FundamentalImprovementMetric.REVENUE,
                current="130",
                current_comparison="100",
                prior="110",
                prior_comparison="100",
                current_one_off="10",
                prior_one_off="10",
            )
        )
        result = fundamental_improvement_definition_v0().calculate(
            {FundamentalImprovementMetric.REVENUE: compiled},
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        component = result.component(FundamentalImprovementMetric.REVENUE)

        self.assertEqual(compiled.level, Decimal(120))
        self.assertEqual(compiled.current_change, Decimal("0.20"))
        self.assertEqual(compiled.prior_change, Decimal(0))
        self.assertEqual(component.acceleration, Decimal("0.20"))

    def test_margin_uses_percentage_point_change_not_relative_growth(self) -> None:
        compiled = FundamentalImprovementInputCompilerV0().compile(
            self.observation(
                FundamentalImprovementMetric.MARGIN,
                current="0.25",
                current_comparison="0.23",
                prior="0.22",
                prior_comparison="0.21",
            )
        )

        self.assertEqual(compiled.current_change, Decimal("0.02"))
        self.assertEqual(compiled.prior_change, Decimal("0.01"))

    def test_zero_base_or_uncontrolled_treatment_is_unavailable_without_zero_fill(self) -> None:
        cases = (
            self.observation(
                FundamentalImprovementMetric.REVENUE,
                current="100",
                current_comparison="0",
                prior="90",
                prior_comparison="80",
            ),
            self.observation(
                FundamentalImprovementMetric.PROFIT,
                current="20",
                current_comparison="10",
                prior="15",
                prior_comparison="9",
                comparison=ImprovementComparison.QOQ,
                window=ImprovementWindow.SINGLE_QUARTER,
                seasonality=SeasonalityTreatment.UNCONTROLLED,
            ),
            self.observation(
                FundamentalImprovementMetric.CASH_FLOW,
                current="20",
                current_comparison="10",
                prior="15",
                prior_comparison="9",
                one_off=OneOffTreatment.INCLUDED_UNADJUSTED,
            ),
        )
        for value in cases:
            with self.subTest(metric=value.metric.value):
                compiled = FundamentalImprovementInputCompilerV0().compile(value)
                self.assertIsNone(compiled.level)
                self.assertIsNone(compiled.current_change)
                self.assertIsNone(compiled.prior_change)
                self.assertTrue(compiled.unavailable_reasons)

    def test_negative_comparison_base_is_unavailable_without_zero_fill(self) -> None:
        compiled = FundamentalImprovementInputCompilerV0().compile(
            self.observation(
                FundamentalImprovementMetric.PROFIT,
                current="10",
                current_comparison="-2",
                prior="8",
                prior_comparison="-1",
            )
        )

        self.assertIsNone(compiled.level)
        self.assertIsNone(compiled.current_change)
        self.assertIn("non-positive comparison base", compiled.unavailable_reasons[0])


class FundamentalImprovementV0DistortionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = fundamental_improvement_definition_v0()

    def test_uncontrolled_distortions_are_partial_and_never_zero_filled(self) -> None:
        values = {
            FundamentalImprovementMetric.REVENUE: component_input(
                FundamentalImprovementMetric.REVENUE,
                level="120",
                current_change="0.20",
                prior_change="0.10",
                comparison=ImprovementComparison.QOQ,
                window=ImprovementWindow.SINGLE_QUARTER,
                seasonality=SeasonalityTreatment.SEASONALLY_ADJUSTED,
            ),
            FundamentalImprovementMetric.PROFIT: component_input(
                FundamentalImprovementMetric.PROFIT,
                level="30",
                current_change="0.50",
                prior_change="0.20",
                comparison=ImprovementComparison.QOQ,
                window=ImprovementWindow.SINGLE_QUARTER,
                seasonality=SeasonalityTreatment.UNCONTROLLED,
            ),
            FundamentalImprovementMetric.MARGIN: component_input(
                FundamentalImprovementMetric.MARGIN,
                level="0.25",
                current_change="0.02",
                prior_change="0.01",
                base_effect=BaseEffectTreatment.PRESENT_UNADJUSTED,
            ),
            FundamentalImprovementMetric.CASH_FLOW: component_input(
                FundamentalImprovementMetric.CASH_FLOW,
                level="25",
                current_change="0.30",
                prior_change="0.10",
                one_off=OneOffTreatment.INCLUDED_UNADJUSTED,
            ),
        }

        result = self.definition.calculate(
            values,
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(result.status, ImprovementResultStatus.PARTIAL)
        self.assertEqual(result.breadth, Decimal(1))
        self.assertEqual(result.confidence, Decimal("0.25"))
        self.assertEqual(
            result.unavailable_metrics,
            (
                FundamentalImprovementMetric.CASH_FLOW,
                FundamentalImprovementMetric.MARGIN,
                FundamentalImprovementMetric.PROFIT,
            ),
        )
        for metric in result.unavailable_metrics:
            component = result.component(metric)
            self.assertIsNone(component.level)
            self.assertIsNone(component.trend)
            self.assertIsNone(component.acceleration)
            self.assertTrue(component.unavailable_reasons)

    def test_no_usable_components_is_unavailable_not_numeric_zero(self) -> None:
        result = self.definition.calculate(
            {},
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(result.status, ImprovementResultStatus.UNAVAILABLE)
        self.assertIsNone(result.breadth)
        self.assertIsNone(result.confidence)
        self.assertEqual(set(result.unavailable_metrics), set(FundamentalImprovementMetric))


class FundamentalImprovementV0ContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.definition = fundamental_improvement_definition_v0()
        self.all_values = {
            metric: component_input(
                metric,
                level="1",
                current_change="0.20",
                prior_change="0.10",
            )
            for metric in FundamentalImprovementMetric
        }

    def test_current_result_is_not_historical_and_strict_requires_pit_inputs(self) -> None:
        current = self.definition.calculate(
            self.all_values,
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertFalse(current.historical_eligible)
        self.assertTrue(any("current" in warning for warning in current.warnings))
        with self.assertRaisesRegex(PermissionError, "pit_verified"):
            self.definition.calculate(
                self.all_values,
                exposures=exposures(),
                data_mode=DataMode.STRICT_HISTORICAL,
            )

        decision_time = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
        strict_values = {
            metric: replace(
                value,
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.PIT_VERIFIED,
                decision_time=decision_time,
                latest_source_available_at=decision_time - timedelta(seconds=1),
            )
            for metric, value in self.all_values.items()
        }
        strict = self.definition.calculate(
            strict_values,
            exposures=exposures(),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        self.assertTrue(strict.historical_eligible)
        self.assertEqual(strict.decision_time, decision_time)
        self.assertLessEqual(strict.latest_input_available_at, strict.decision_time)

        with self.assertRaisesRegex(ValueError, "available_at cannot exceed decision_time"):
            replace(
                next(iter(strict_values.values())),
                latest_source_available_at=decision_time + timedelta(seconds=1),
            )

    def test_units_periods_and_provenance_fail_closed(self) -> None:
        revenue = self.all_values[FundamentalImprovementMetric.REVENUE]
        invalid_builders = (
            lambda: replace(revenue, level_unit=MetricUnit.RATIO, currency=None),
            lambda: replace(revenue, prior_period_end=date(2024, 6, 30)),
            lambda: replace(
                revenue,
                provenance=replace(revenue.provenance, mapping_version_id=""),
            ),
        )
        for invalid_builder in invalid_builders:
            with (
                self.subTest(invalid_builder=invalid_builder),
                self.assertRaises((TypeError, ValueError)),
            ):
                invalid_builder()

    def test_missing_value_is_unavailable_and_requires_an_explicit_reason(self) -> None:
        with self.assertRaisesRegex(ValueError, "unavailable_reasons"):
            component_input(
                FundamentalImprovementMetric.REVENUE,
                level=None,
                current_change="0.20",
                prior_change="0.10",
            )

        unavailable = component_input(
            FundamentalImprovementMetric.REVENUE,
            level=None,
            current_change="0.20",
            prior_change="0.10",
            unavailable_reasons=("current revenue level is missing",),
        )
        result = self.definition.calculate(
            {FundamentalImprovementMetric.REVENUE: unavailable},
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        revenue = result.component(FundamentalImprovementMetric.REVENUE)
        self.assertIsNone(revenue.level)
        self.assertIsNone(revenue.trend)
        self.assertIsNone(revenue.acceleration)

    def test_size_industry_and_beta_are_exposures_not_formula_inputs(self) -> None:
        first = self.definition.calculate(
            self.all_values,
            exposures=exposures(industry="C30", size="23.5", beta="1.1"),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        second = self.definition.calculate(
            self.all_values,
            exposures=exposures(industry=None, size=None, beta=None),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(first.breadth, second.breadth)
        self.assertEqual(first.confidence, second.confidence)
        self.assertEqual(second.exposures.missing_exposure_names, ("industry", "size", "beta"))
        self.assertEqual(
            self.definition.neutralization_exposure_names,
            ("industry", "size", "beta"),
        )
        self.assertEqual(
            first.scientific_status,
            ImprovementScientificStatus.NOT_EVALUATED,
        )


if __name__ == "__main__":
    unittest.main()
