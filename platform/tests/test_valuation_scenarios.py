import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import ValuationExpectationMetric
from a_share_platform.domain.valuation_scenarios import (
    ScenarioScientificStatus,
    SensitivityDirection,
    ValuationScenario,
    ValuationScenarioInput,
    ValuationScenarioProvenance,
    ValuationScenarioSensitivityDefinition,
    ValuationScenarioSensitivityResult,
    ValuationScenarioSetStatus,
    ValuationScenarioStatus,
    ValuationSensitivityInterval,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def provenance(scenario: ValuationScenario) -> ValuationScenarioProvenance:
    return ValuationScenarioProvenance(
        dataset_version_id="dataset:scenario-inputs:2025q1:v1",
        source_observation_ids=(f"observation:{scenario.value}:2025q1:v1",),
        content_hashes=(HASH_A if scenario is ValuationScenario.BASE else HASH_B,),
    )


def scenario_input(
    scenario: ValuationScenario,
    lower: str | None,
    upper: str | None,
    *,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    unavailable_reasons: tuple[str, ...] = (),
    decision_time: datetime | None = None,
    available_at: datetime | None = None,
) -> ValuationScenarioInput:
    return ValuationScenarioInput(
        scenario=scenario,
        driver_lower=None if lower is None else Decimal(lower),
        driver_upper=None if upper is None else Decimal(upper),
        driver_unit=MetricUnit.RATIO,
        assumptions=(f"{scenario.value} driver interval approved:v1",),
        provenance=provenance(scenario),
        data_mode=data_mode,
        trust_state=trust_state,
        unavailable_reasons=unavailable_reasons,
        decision_time=decision_time,
        latest_source_available_at=available_at,
    )


def definition(
    *,
    direction: SensitivityDirection = SensitivityDirection.POSITIVE,
    coefficient: str = "0.5",
    intercept: str = "0.08",
) -> ValuationScenarioSensitivityDefinition:
    return ValuationScenarioSensitivityDefinition(
        method_id="valuation-sensitivity:affine-expectation:v1",
        method_version="v1",
        driver_name="revenue_growth",
        driver_unit=MetricUnit.RATIO,
        expectation_metric=ValuationExpectationMetric.GROWTH,
        output_unit=MetricUnit.RATIO,
        direction=direction,
        coefficient=Decimal(coefficient),
        intercept=Decimal(intercept),
        method_assumptions=("Affine response is a bounded sensitivity, not a target price.",),
        invalidation_conditions=("The affine response is invalid outside the declared intervals.",),
        scientific_status=ScenarioScientificStatus.NOT_EVALUATED,
    )


def output_interval(
    result: ValuationScenarioSensitivityResult,
    scenario: ValuationScenario,
) -> ValuationSensitivityInterval:
    interval = result.component(scenario).output_interval
    assert interval is not None
    return interval


class ValuationScenarioSensitivityTest(unittest.TestCase):
    def test_positive_sensitivity_calculates_base_bull_bear_decimal_intervals(self) -> None:
        result = definition().calculate(
            (
                scenario_input(ValuationScenario.BASE, "0.04", "0.06"),
                scenario_input(ValuationScenario.BULL, "0.08", "0.10"),
                scenario_input(ValuationScenario.BEAR, "0.00", "0.02"),
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(result.status, ValuationScenarioSetStatus.QUANTIFIED)
        bear = output_interval(result, ValuationScenario.BEAR)
        base = output_interval(result, ValuationScenario.BASE)
        bull = output_interval(result, ValuationScenario.BULL)
        self.assertEqual(
            (bear.lower, bear.upper),
            (Decimal("0.080"), Decimal("0.090")),
        )
        self.assertEqual(
            (base.lower, base.upper),
            (Decimal("0.100"), Decimal("0.110")),
        )
        self.assertEqual(
            (bull.lower, bull.upper),
            (Decimal("0.120"), Decimal("0.130")),
        )
        self.assertTrue(all(isinstance(value, Decimal) for value in result.sensitivity_points))
        self.assertFalse(hasattr(result, "target_price"))
        self.assertEqual(result.method_version, "v1")
        self.assertTrue(result.definition_hash.startswith("sha256:"))
        self.assertEqual(
            result.input_dataset_version_ids,
            ("dataset:scenario-inputs:2025q1:v1",),
        )
        self.assertEqual(result.input_content_hashes, (HASH_A, HASH_B))
        self.assertIn("Affine response", result.assumptions[0])
        self.assertEqual(result.scientific_status, ScenarioScientificStatus.NOT_EVALUATED)
        self.assertFalse(result.historical_eligible)
        self.assertTrue(any("current" in warning for warning in result.warnings))

    def test_negative_sensitivity_preserves_bear_base_bull_outcome_monotonicity(self) -> None:
        result = definition(
            direction=SensitivityDirection.NEGATIVE,
            coefficient="-0.5",
            intercept="0.20",
        ).calculate(
            (
                scenario_input(ValuationScenario.BULL, "0.02", "0.04"),
                scenario_input(ValuationScenario.BASE, "0.08", "0.10"),
                scenario_input(ValuationScenario.BEAR, "0.14", "0.16"),
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        bear = output_interval(result, ValuationScenario.BEAR)
        base = output_interval(result, ValuationScenario.BASE)
        bull = output_interval(result, ValuationScenario.BULL)
        self.assertLessEqual(bear.lower, base.lower)
        self.assertLessEqual(base.lower, bull.lower)
        self.assertLessEqual(bear.upper, base.upper)
        self.assertLessEqual(base.upper, bull.upper)
        self.assertEqual((bull.lower, bull.upper), (Decimal("0.180"), Decimal("0.190")))

    def test_non_monotonic_scenario_intervals_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "monotonic"):
            definition().calculate(
                (
                    scenario_input(ValuationScenario.BEAR, "0.00", "0.02"),
                    scenario_input(ValuationScenario.BASE, "0.08", "0.10"),
                    scenario_input(ValuationScenario.BULL, "0.04", "0.06"),
                ),
                data_mode=DataMode.CURRENT_RESEARCH,
            )

    def test_unavailable_scenario_is_explicit_and_never_zero_filled(self) -> None:
        result = definition().calculate(
            (
                scenario_input(ValuationScenario.BEAR, "0.00", "0.02"),
                scenario_input(ValuationScenario.BASE, "0.04", "0.06"),
                scenario_input(
                    ValuationScenario.BULL,
                    None,
                    None,
                    unavailable_reasons=("bull assumptions are not qualified",),
                ),
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )

        self.assertEqual(result.status, ValuationScenarioSetStatus.PARTIAL)
        bull = result.component(ValuationScenario.BULL)
        self.assertEqual(bull.status, ValuationScenarioStatus.UNAVAILABLE)
        self.assertIsNone(bull.driver_interval)
        self.assertIsNone(bull.output_interval)
        self.assertEqual(bull.unavailable_reasons, ("bull assumptions are not qualified",))
        self.assertIsNotNone(bull.provenance)

        unavailable = definition().calculate(
            tuple(
                scenario_input(
                    scenario,
                    None,
                    None,
                    unavailable_reasons=(f"{scenario.value} inputs are unavailable",),
                )
                for scenario in ValuationScenario
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(unavailable.status, ValuationScenarioSetStatus.UNAVAILABLE)
        self.assertEqual(unavailable.sensitivity_points, ())

    def test_requires_exactly_one_base_bull_and_bear(self) -> None:
        with self.assertRaisesRegex(ValueError, "base, bull, and bear"):
            definition().calculate(
                (
                    scenario_input(ValuationScenario.BASE, "0.04", "0.06"),
                    scenario_input(ValuationScenario.BULL, "0.08", "0.10"),
                ),
                data_mode=DataMode.CURRENT_RESEARCH,
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            definition().calculate(
                (
                    scenario_input(ValuationScenario.BASE, "0.04", "0.06"),
                    scenario_input(ValuationScenario.BASE, "0.04", "0.06"),
                    scenario_input(ValuationScenario.BEAR, "0.00", "0.02"),
                ),
                data_mode=DataMode.CURRENT_RESEARCH,
            )

    def test_decimal_interval_and_method_contracts_fail_closed(self) -> None:
        valid = scenario_input(ValuationScenario.BASE, "0.04", "0.06")
        with self.assertRaisesRegex(TypeError, "Decimal"):
            replace(valid, driver_lower=0.04)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "upper"):
            replace(valid, driver_lower=Decimal("0.07"))
        with self.assertRaisesRegex(ValueError, "unavailable_reasons"):
            replace(valid, driver_lower=None, driver_upper=None)
        with self.assertRaisesRegex(TypeError, "Decimal"):
            replace(definition(), coefficient=0.5)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "direction"):
            replace(definition(), coefficient=Decimal("-0.5"))

    def test_lineage_assumptions_and_version_are_mandatory_and_definition_is_stable(self) -> None:
        first = definition()
        second = definition()
        self.assertEqual(first.definition_hash, second.definition_hash)
        with self.assertRaisesRegex(ValueError, "method_version"):
            replace(first, method_version="")
        with self.assertRaisesRegex(ValueError, "method_assumptions"):
            replace(first, method_assumptions=())
        with self.assertRaisesRegex(ValueError, "content_hashes"):
            replace(
                provenance(ValuationScenario.BASE),
                content_hashes=("not-a-hash",),
            )

    def test_current_inputs_cannot_be_relabelled_strict_and_pit_clocks_are_enforced(self) -> None:
        current = tuple(
            scenario_input(scenario, lower, upper)
            for scenario, lower, upper in (
                (ValuationScenario.BEAR, "0.00", "0.02"),
                (ValuationScenario.BASE, "0.04", "0.06"),
                (ValuationScenario.BULL, "0.08", "0.10"),
            )
        )
        with self.assertRaisesRegex(PermissionError, "relabelled"):
            definition().calculate(current, data_mode=DataMode.STRICT_HISTORICAL)

        decision_time = datetime(2025, 4, 30, 15, 0, tzinfo=UTC)
        available_at = decision_time - timedelta(seconds=1)
        strict = tuple(
            replace(
                value,
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.PIT_VERIFIED,
                decision_time=decision_time,
                latest_source_available_at=available_at,
            )
            for value in current
        )
        result = definition().calculate(strict, data_mode=DataMode.STRICT_HISTORICAL)
        self.assertTrue(result.historical_eligible)
        self.assertEqual(result.decision_time, decision_time)
        self.assertEqual(result.latest_input_available_at, available_at)
        self.assertFalse(result.warnings)

        with self.assertRaisesRegex(ValueError, "available_at cannot exceed decision_time"):
            replace(
                strict[0],
                latest_source_available_at=decision_time + timedelta(seconds=1),
            )
        with self.assertRaisesRegex(PermissionError, "pit_verified"):
            replace(strict[0], trust_state=DataTrustState.NORMALIZED_CURRENT)


if __name__ == "__main__":
    unittest.main()
