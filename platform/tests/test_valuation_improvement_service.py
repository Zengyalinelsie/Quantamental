import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from a_share_platform.adapters.memory.valuation_inputs import (
    MemoryValuationImprovementInputSource,
    UnavailableValuationImprovementInputSource,
)
from a_share_platform.application.valuation_improvement import (
    ValuationImprovementAnalysisStatus,
    ValuationImprovementComponentStatus,
    ValuationImprovementOrchestrationService,
)
from a_share_platform.domain.features import FeaturePeriod
from a_share_platform.domain.fundamental_improvement import (
    BaseEffectTreatment,
    FundamentalImprovementExposures,
    FundamentalImprovementInput,
    FundamentalImprovementMetric,
    ImprovementComparison,
    ImprovementInputProvenance,
    ImprovementWindow,
    OneOffTreatment,
    SeasonalityTreatment,
)
from a_share_platform.domain.industry_templates import IndustryTemplateId
from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import (
    ValuationExpectationMetric,
    ValuationExpectationRangeInput,
    ValuationExpectationSource,
    ValuationExposures,
    ValuationInputProvenance,
    ValuationMetric,
    ValuationMetricInput,
)
from a_share_platform.domain.valuation_scenarios import (
    ScenarioScientificStatus,
    SensitivityDirection,
    ValuationScenario,
    ValuationScenarioInput,
    ValuationScenarioProvenance,
    ValuationScenarioSensitivityDefinition,
)
from a_share_platform.ports.valuation_inputs import (
    ValuationImprovementInputBundle,
    ValuationImprovementInputRequest,
)

HASH_A = "sha256:" + "a" * 64
DECISION_TIME = datetime(2025, 4, 30, 15, 0, tzinfo=UTC)
AVAILABLE_AT = DECISION_TIME - timedelta(seconds=1)
DATASET_IDS = (
    "dataset:improvement:2025q1:v1",
    "dataset:scenario:2025q1:v1",
    "dataset:valuation:2025q1:v1",
)


def valuation_provenance(name: str) -> ValuationInputProvenance:
    return ValuationInputProvenance(
        dataset_version_id="dataset:valuation:2025q1:v1",
        method_id=f"method:{name}",
        method_version="v1",
        source_observation_ids=(f"observation:{name}:v1",),
        content_hashes=(HASH_A,),
    )


def valuation_metric_input(
    metric: ValuationMetric,
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
) -> ValuationMetricInput:
    specifications = {
        ValuationMetric.EARNINGS_TO_PRICE: (
            "5",
            "50",
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.TTM,
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
        ),
        ValuationMetric.BOOK_TO_PRICE: (
            "20",
            "50",
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
        ),
        ValuationMetric.FREE_CASH_FLOW_YIELD: (
            "4",
            "50",
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.TTM,
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
        ),
        ValuationMetric.ENTERPRISE_VALUE_TO_EBIT: (
            "120",
            "20",
            MetricUnit.CURRENCY,
            FeaturePeriod.INSTANT,
            MetricUnit.CURRENCY,
            FeaturePeriod.TTM,
        ),
    }
    (
        numerator,
        denominator,
        numerator_unit,
        numerator_period,
        denominator_unit,
        denominator_period,
    ) = specifications[metric]
    return ValuationMetricInput(
        metric=metric,
        numerator=Decimal(numerator),
        denominator=Decimal(denominator),
        numerator_unit=numerator_unit,
        numerator_period=numerator_period,
        denominator_unit=denominator_unit,
        denominator_period=denominator_period,
        currency="CNY",
        provenance=valuation_provenance(metric.value),
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
    )


def expectation(
    source: ValuationExpectationSource,
    lower: str,
    upper: str,
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
) -> ValuationExpectationRangeInput:
    return ValuationExpectationRangeInput(
        source=source,
        expectation_metric=ValuationExpectationMetric.GROWTH,
        lower=Decimal(lower),
        upper=Decimal(upper),
        unit=MetricUnit.RATIO,
        assumptions=(f"{source.value} assumptions:v1",),
        invalidation_conditions=(f"{source.value} invalidation:v1",),
        provenance=valuation_provenance(source.value),
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
    )


def improvement_input(
    metric: FundamentalImprovementMetric,
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
) -> FundamentalImprovementInput:
    is_margin = metric is FundamentalImprovementMetric.MARGIN
    return FundamentalImprovementInput(
        metric=metric,
        level=Decimal("0.25" if is_margin else "100"),
        current_change=Decimal("0.20"),
        prior_change=Decimal("0.10"),
        level_unit=MetricUnit.RATIO if is_margin else MetricUnit.CURRENCY,
        change_unit=MetricUnit.RATIO,
        currency=None if is_margin else "CNY",
        comparison=ImprovementComparison.YOY,
        window=ImprovementWindow.TTM,
        current_period_end=date(2025, 3, 31),
        current_comparison_period_end=date(2024, 3, 31),
        prior_period_end=date(2024, 12, 31),
        prior_comparison_period_end=date(2023, 12, 31),
        seasonality_treatment=SeasonalityTreatment.YOY_COMPARABLE,
        base_effect_treatment=BaseEffectTreatment.ABSENT,
        one_off_treatment=OneOffTreatment.EXCLUDED,
        provenance=ImprovementInputProvenance(
            dataset_version_id="dataset:improvement:2025q1:v1",
            source_version_id="source:financial:v1",
            mapping_version_id="mapping:financial:v1",
            metric_definition_id=f"metric:{metric.value}",
            metric_definition_version="v1",
            source_fact_ids=(f"fact:{metric.value}:2025q1",),
            content_hashes=(HASH_A,),
        ),
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
    )


def scenario_input(
    scenario: ValuationScenario,
    lower: str | None,
    upper: str | None,
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
    unavailable_reasons: tuple[str, ...] = (),
) -> ValuationScenarioInput:
    return ValuationScenarioInput(
        scenario=scenario,
        driver_lower=None if lower is None else Decimal(lower),
        driver_upper=None if upper is None else Decimal(upper),
        driver_unit=MetricUnit.RATIO,
        assumptions=(f"{scenario.value} assumptions:v1",),
        provenance=ValuationScenarioProvenance(
            dataset_version_id="dataset:scenario:2025q1:v1",
            source_observation_ids=(f"scenario-observation:{scenario.value}:v1",),
            content_hashes=(HASH_A,),
        ),
        data_mode=data_mode,
        trust_state=trust_state,
        unavailable_reasons=unavailable_reasons,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
    )


def scenario_definition() -> ValuationScenarioSensitivityDefinition:
    return ValuationScenarioSensitivityDefinition(
        method_id="valuation-sensitivity:affine-expectation:v1",
        method_version="v1",
        driver_name="revenue_growth",
        driver_unit=MetricUnit.RATIO,
        expectation_metric=ValuationExpectationMetric.GROWTH,
        output_unit=MetricUnit.RATIO,
        direction=SensitivityDirection.POSITIVE,
        coefficient=Decimal("0.5"),
        intercept=Decimal("0.08"),
        method_assumptions=("Affine response is a bounded sensitivity.",),
        invalidation_conditions=("Invalid outside declared intervals.",),
        scientific_status=ScenarioScientificStatus.NOT_EVALUATED,
    )


def bundle(
    *,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    bull_available: bool = True,
) -> ValuationImprovementInputBundle:
    bull = (
        scenario_input(
            ValuationScenario.BULL,
            "0.08",
            "0.10",
            data_mode=data_mode,
            trust_state=trust_state,
        )
        if bull_available
        else scenario_input(
            ValuationScenario.BULL,
            None,
            None,
            data_mode=data_mode,
            trust_state=trust_state,
            unavailable_reasons=("bull inputs are unavailable",),
        )
    )
    return ValuationImprovementInputBundle(
        bundle_version_id="bundle:security:000001:2025-04-30:v1",
        security_id="security:000001.XSHE",
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
        data_mode=data_mode,
        trust_state=trust_state,
        dataset_version_ids=DATASET_IDS,
        industry_template_id=IndustryTemplateId.NON_FINANCIAL_GENERAL,
        valuation_formula_version="v0",
        improvement_formula_version="v0",
        scenario_method_id="valuation-sensitivity:affine-expectation:v1",
        scenario_method_version="v1",
        valuation_metric_inputs=tuple(
            valuation_metric_input(metric, data_mode=data_mode, trust_state=trust_state)
            for metric in ValuationMetric
        ),
        market_implied=expectation(
            ValuationExpectationSource.MARKET_IMPLIED,
            "0.08",
            "0.10",
            data_mode=data_mode,
            trust_state=trust_state,
        ),
        fundamental_anchor=expectation(
            ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
            "0.12",
            "0.15",
            data_mode=data_mode,
            trust_state=trust_state,
        ),
        valuation_exposures=ValuationExposures(
            industry_code="C30",
            log_market_cap=Decimal("23.5"),
            beta=Decimal("1.1"),
        ),
        currency="CNY",
        comparable_set_version_id="comparable-set:C30:2025q1:v1",
        improvement_inputs=tuple(
            improvement_input(metric, data_mode=data_mode, trust_state=trust_state)
            for metric in FundamentalImprovementMetric
        ),
        improvement_exposures=FundamentalImprovementExposures(
            industry_code="C30",
            log_market_cap=Decimal("23.5"),
            beta=Decimal("1.1"),
        ),
        scenario_inputs=(
            scenario_input(
                ValuationScenario.BEAR,
                "0.00",
                "0.02",
                data_mode=data_mode,
                trust_state=trust_state,
            ),
            scenario_input(
                ValuationScenario.BASE,
                "0.04",
                "0.06",
                data_mode=data_mode,
                trust_state=trust_state,
            ),
            bull,
        ),
    )


def request(
    *,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
) -> ValuationImprovementInputRequest:
    return ValuationImprovementInputRequest(
        security_id="security:000001.XSHE",
        decision_time=DECISION_TIME,
        data_mode=data_mode,
        trust_state=trust_state,
        bundle_version_id="bundle:security:000001:2025-04-30:v1",
    )


class FixedSource:
    def __init__(self, value: ValuationImprovementInputBundle | None) -> None:
        self.value = value

    def load(
        self,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        return self.value


class ValuationImprovementOrchestrationServiceTest(unittest.TestCase):
    def test_executes_three_provider_neutral_domain_calculations_from_frozen_bundle(self) -> None:
        frozen = bundle()
        service = ValuationImprovementOrchestrationService(
            MemoryValuationImprovementInputSource((frozen,)),
            scenario_definition(),
        )

        result = service.evaluate(request())

        self.assertEqual(result.status, ValuationImprovementAnalysisStatus.QUANTIFIED)
        self.assertEqual(result.security_id, "security:000001.XSHE")
        self.assertEqual(result.decision_time, DECISION_TIME)
        self.assertEqual(result.bundle_version_id, frozen.bundle_version_id)
        self.assertEqual(result.input_dataset_version_ids, DATASET_IDS)
        self.assertIs(result.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(result.valuation_status, ValuationImprovementComponentStatus.QUANTIFIED)
        self.assertEqual(result.improvement_status, ValuationImprovementComponentStatus.QUANTIFIED)
        self.assertEqual(result.scenario_status, ValuationImprovementComponentStatus.QUANTIFIED)
        self.assertIsNotNone(result.valuation_result)
        self.assertIsNotNone(result.improvement_result)
        self.assertIsNotNone(result.scenario_result)
        self.assertEqual(result.unavailable_reasons, ())
        self.assertFalse(result.historical_eligible)
        self.assertTrue(any("current" in value for value in result.warnings))
        self.assertEqual(result.scientific_status.value, "not_evaluated")

    def test_unavailable_source_returns_explicit_unavailable_without_runtime_fixture(self) -> None:
        source = UnavailableValuationImprovementInputSource()
        service = ValuationImprovementOrchestrationService(source, scenario_definition())

        result = service.evaluate(request())

        self.assertEqual(result.status, ValuationImprovementAnalysisStatus.UNAVAILABLE)
        self.assertEqual(result.valuation_status, ValuationImprovementComponentStatus.UNAVAILABLE)
        self.assertEqual(result.improvement_status, ValuationImprovementComponentStatus.UNAVAILABLE)
        self.assertEqual(result.scenario_status, ValuationImprovementComponentStatus.UNAVAILABLE)
        self.assertIsNone(result.valuation_result)
        self.assertIsNone(result.improvement_result)
        self.assertIsNone(result.scenario_result)
        self.assertEqual(result.input_dataset_version_ids, ())
        self.assertIs(result.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertTrue(result.unavailable_reasons)
        self.assertEqual(source.load_count, 1)

    def test_request_and_returned_bundle_identity_cutoff_trust_mode_and_version_must_match(
        self,
    ) -> None:
        current = bundle()
        mismatches = (
            (replace(current, security_id="security:000002.XSHE"), request(), "security_id"),
            (
                current,
                replace(request(), decision_time=DECISION_TIME + timedelta(seconds=1)),
                "decision_time",
            ),
            (
                current,
                replace(request(), trust_state=DataTrustState.PIT_VERIFIED),
                "trust_state",
            ),
            (
                replace(current, bundle_version_id="bundle:other:v1"),
                request(),
                "bundle_version_id",
            ),
            (
                current,
                request(
                    data_mode=DataMode.STRICT_HISTORICAL,
                    trust_state=DataTrustState.PIT_VERIFIED,
                ),
                "data_mode",
            ),
        )
        for returned, query, message in mismatches:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(
                    (PermissionError if message in {"trust_state", "data_mode"} else ValueError),
                    message,
                ),
            ):
                ValuationImprovementOrchestrationService(
                    FixedSource(returned),
                    scenario_definition(),
                ).evaluate(query)

    def test_bundle_rejects_internal_cutoff_trust_dataset_and_duplicate_inconsistency(self) -> None:
        valid = bundle()
        first = valid.valuation_metric_inputs[0]
        earlier = DECISION_TIME - timedelta(days=1)
        invalid_builders = (
            lambda: replace(valid, dataset_version_ids=("dataset:not-the-inputs:v1",)),
            lambda: replace(
                valid,
                latest_source_available_at=AVAILABLE_AT - timedelta(seconds=1),
            ),
            lambda: replace(
                valid,
                valuation_metric_inputs=(
                    replace(
                        first,
                        decision_time=earlier,
                        latest_source_available_at=earlier - timedelta(seconds=1),
                    ),
                    *valid.valuation_metric_inputs[1:],
                ),
            ),
            lambda: replace(
                valid,
                valuation_metric_inputs=(
                    replace(first, trust_state=DataTrustState.PIT_VERIFIED),
                    *valid.valuation_metric_inputs[1:],
                ),
            ),
            lambda: replace(
                valid,
                valuation_metric_inputs=(*valid.valuation_metric_inputs, first),
            ),
        )
        for invalid_builder in invalid_builders:
            with self.subTest(invalid_builder=invalid_builder), self.assertRaises(ValueError):
                invalid_builder()

    def test_domain_definition_versions_must_match_frozen_bundle_versions(self) -> None:
        valid = bundle()
        mismatches = (
            replace(valid, valuation_formula_version="not-v0"),
            replace(valid, improvement_formula_version="not-v0"),
            replace(valid, scenario_method_id="another-method"),
            replace(valid, scenario_method_version="v2"),
        )
        for mismatch in mismatches:
            with (
                self.subTest(mismatch=mismatch),
                self.assertRaisesRegex(ValueError, "version|method"),
            ):
                ValuationImprovementOrchestrationService(
                    FixedSource(mismatch),
                    scenario_definition(),
                ).evaluate(request())

    def test_strict_historical_requires_pit_and_preserves_cutoff(self) -> None:
        with self.assertRaisesRegex(PermissionError, "pit_verified"):
            request(
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )

        strict_bundle = bundle(
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
        )
        strict_request = request(
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
        )
        result = ValuationImprovementOrchestrationService(
            MemoryValuationImprovementInputSource((strict_bundle,)),
            scenario_definition(),
        ).evaluate(strict_request)

        self.assertTrue(result.historical_eligible)
        self.assertIs(result.trust_state, DataTrustState.PIT_VERIFIED)
        self.assertEqual(result.decision_time, DECISION_TIME)
        self.assertEqual(result.latest_input_available_at, AVAILABLE_AT)
        self.assertTrue(result.valuation_result.historical_eligible)  # type: ignore[union-attr]
        self.assertTrue(result.improvement_result.historical_eligible)  # type: ignore[union-attr]
        self.assertTrue(result.scenario_result.historical_eligible)  # type: ignore[union-attr]

        with self.assertRaisesRegex(PermissionError, "data_mode"):
            ValuationImprovementOrchestrationService(
                FixedSource(bundle()),
                scenario_definition(),
            ).evaluate(strict_request)

    def test_partial_component_remains_partial_and_unavailable_is_not_zero(self) -> None:
        partial = bundle(bull_available=False)
        result = ValuationImprovementOrchestrationService(
            MemoryValuationImprovementInputSource((partial,)),
            scenario_definition(),
        ).evaluate(request())

        self.assertEqual(result.status, ValuationImprovementAnalysisStatus.PARTIAL)
        self.assertEqual(result.scenario_status, ValuationImprovementComponentStatus.PARTIAL)
        self.assertIsNotNone(result.scenario_result)
        bull = result.scenario_result.component(ValuationScenario.BULL)  # type: ignore[union-attr]
        self.assertIsNone(bull.output_interval)
        self.assertTrue(bull.unavailable_reasons)

    def test_memory_source_is_exact_keyed_and_rejects_duplicate_frozen_bundles(self) -> None:
        frozen = bundle()
        source = MemoryValuationImprovementInputSource((frozen,))
        self.assertIs(source.load(request()), frozen)
        self.assertIsNone(source.load(replace(request(), bundle_version_id="bundle:missing:v1")))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            MemoryValuationImprovementInputSource((frozen, frozen))


if __name__ == "__main__":
    unittest.main()
