import importlib.util
import math
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from a_share_platform.domain.factor_panel_statistics import (
    FamaMacBethObservation,
    FamaMacBethSpec,
    RegimeSubperiodObservation,
    RegimeSubperiodSpec,
    fama_macbeth,
    regime_subperiod_robustness,
)
from a_share_platform.domain.factor_statistics import StatisticStatus
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

BASE_TIME = datetime(2024, 1, 2, 9, 30, tzinfo=UTC)


def panel_row(
    period: int,
    entity: str,
    quality: float | None,
    value: float | None,
    outcome: float | None,
    *,
    missing_reason: str | None = None,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
) -> FamaMacBethObservation:
    decision_time = BASE_TIME + timedelta(days=period * 30)
    return FamaMacBethObservation(
        period_id=f"period:{period}",
        entity_id=entity,
        forward_return=outcome,
        factor_values=(("quality", quality), ("value", value)),
        factor_version_ids=(
            ("quality", "feature:quality:v1"),
            ("value", "feature:value:v1"),
        ),
        label_version_id="label:forward-return-20d:v1",
        data_mode=data_mode,
        factor_trust_state=trust_state,
        label_trust_state=trust_state,
        decision_time=decision_time,
        factor_available_at=decision_time - timedelta(seconds=1),
        label_outcome_at=decision_time + timedelta(days=20),
        missing_reason=missing_reason,
    )


def exact_period(
    period: int,
    *,
    intercept: float,
    quality_beta: float,
    value_beta: float,
) -> tuple[FamaMacBethObservation, ...]:
    factors = (("A", 0.0, 0.0), ("B", 1.0, 0.0), ("C", 0.0, 1.0), ("D", 1.0, 1.0))
    return tuple(
        panel_row(
            period,
            entity,
            quality,
            value,
            intercept + quality_beta * quality + value_beta * value,
        )
        for entity, quality, value in factors
    )


def robustness_row(
    period: int,
    value: float | None,
    regime: str,
    subperiod: str,
    *,
    missing_reason: str | None = None,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
) -> RegimeSubperiodObservation:
    decision_time = BASE_TIME + timedelta(days=period * 30)
    return RegimeSubperiodObservation(
        period_id=f"period:{period}",
        value=value,
        regime_id=regime,
        subperiod_id=subperiod,
        statistic_version_id="fama-macbeth:quality-coefficient:v1",
        data_mode=data_mode,
        factor_trust_state=trust_state,
        label_trust_state=trust_state,
        decision_time=decision_time,
        factor_available_at=decision_time - timedelta(seconds=1),
        label_outcome_at=decision_time + timedelta(days=20),
        missing_reason=missing_reason,
    )


class FamaMacBethTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = FamaMacBethSpec(
            factor_names=("quality", "value"),
            include_intercept=True,
            minimum_cross_section_size=4,
            minimum_period_count=3,
            rank_tolerance=1e-12,
            formula_version="cross-sectional-ols-then-time-mean:v1",
            standard_error_version="sample-sd-over-sqrt-periods:v1",
        )

    def test_two_factor_coefficients_match_hand_math_and_numpy(self) -> None:
        parameters = (
            (0.01, 0.02, 0.03),
            (0.02, 0.04, 0.01),
            (0.00, 0.03, 0.02),
        )
        rows = tuple(
            row
            for period, values in enumerate(parameters, start=1)
            for row in exact_period(
                period,
                intercept=values[0],
                quality_beta=values[1],
                value_beta=values[2],
            )
        )

        result = fama_macbeth(
            rows,
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(result.valid_period_count, 3)
        self.assertEqual(result.excluded_period_ids, ())
        self.assertAlmostEqual(result.coefficient("intercept").mean, 0.01)
        self.assertAlmostEqual(result.coefficient("quality").mean, 0.03)
        self.assertAlmostEqual(result.coefficient("value").mean, 0.02)
        self.assertAlmostEqual(
            result.coefficient("quality").standard_error or 0,
            0.01 / math.sqrt(3),
        )
        self.assertTrue(all(value.design_rank == 3 for value in result.period_results))
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            design = np.asarray(
                ((1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (1.0, 0.0, 1.0), (1.0, 1.0, 1.0))
            )
            expected = np.asarray(
                [
                    np.linalg.lstsq(
                        design,
                        np.asarray(
                            [
                                intercept,
                                intercept + quality,
                                intercept + value,
                                intercept + quality + value,
                            ]
                        ),
                        rcond=1e-12,
                    )[0]
                    for intercept, quality, value in parameters
                ]
            ).mean(axis=0)
            np.testing.assert_allclose(
                [
                    result.coefficient("intercept").mean,
                    result.coefficient("quality").mean,
                    result.coefficient("value").mean,
                ],
                expected,
                rtol=0,
                atol=1e-12,
            )

    def test_rank_deficient_and_missing_periods_are_explicit_not_zero_filled(self) -> None:
        valid = exact_period(1, intercept=0.01, quality_beta=0.02, value_beta=0.03)
        rank_deficient = tuple(
            panel_row(2, str(index), x, 2 * x, 0.01 + 0.02 * x)
            for index, x in enumerate((0.0, 1.0, 2.0, 3.0), start=1)
        )
        missing = (
            panel_row(3, "A", 0.0, 0.0, 0.01),
            panel_row(3, "B", 1.0, 0.0, None, missing_reason="label missing"),
            panel_row(3, "C", 0.0, 1.0, 0.03),
            panel_row(3, "D", 1.0, 1.0, 0.05),
        )

        result = fama_macbeth(
            (*valid, *rank_deficient, *missing),
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        self.assertEqual(result.coefficients, ())
        self.assertEqual(result.valid_period_count, 1)
        self.assertEqual(result.excluded_period_ids, ("period:2", "period:3"))
        deficient = next(value for value in result.period_results if value.period_id == "period:2")
        self.assertEqual(deficient.status, StatisticStatus.UNAVAILABLE)
        self.assertLess(deficient.design_rank, deficient.required_rank)
        self.assertTrue(deficient.unavailable_reason)

    def test_current_cannot_be_relabelled_and_strict_clock_is_enforced(self) -> None:
        current = tuple(
            replace(
                row,
                data_mode=DataMode.CURRENT_RESEARCH,
                factor_trust_state=DataTrustState.NORMALIZED_CURRENT,
                label_trust_state=DataTrustState.NORMALIZED_CURRENT,
            )
            for row in exact_period(1, intercept=0.01, quality_beta=0.02, value_beta=0.03)
        )
        with self.assertRaisesRegex(PermissionError, "relabelled|pit_verified"):
            fama_macbeth(
                current,
                spec=self.spec,
                data_mode=DataMode.STRICT_HISTORICAL,
            )
        with self.assertRaisesRegex(ValueError, "available_at cannot exceed decision_time"):
            replace(
                current[0],
                factor_available_at=current[0].decision_time + timedelta(seconds=1),
            )

    def test_period_artifacts_are_deterministic_when_input_order_changes(self) -> None:
        rows = tuple(
            row
            for period in (1, 2, 3)
            for row in exact_period(
                period,
                intercept=period / 100,
                quality_beta=0.02,
                value_beta=0.03,
            )
        )

        forward = fama_macbeth(
            rows,
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        backward = fama_macbeth(
            tuple(reversed(rows)),
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(forward, backward)
        self.assertEqual(
            tuple(value.period_id for value in forward.period_results),
            ("period:1", "period:2", "period:3"),
        )


class RegimeSubperiodRobustnessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = RegimeSubperiodSpec(
            minimum_observations_per_slice=2,
            minimum_regime_count=2,
            minimum_subperiod_count=2,
            formula_version="slice-arithmetic-mean-and-sample-sd:v1",
            regime_definition_version="regime:bull-bear:v1",
            subperiod_policy_version="subperiod:early-late:v1",
        )

    def test_regime_and_subperiod_means_match_hand_math_and_numpy(self) -> None:
        rows = (
            robustness_row(1, 0.10, "bull", "early"),
            robustness_row(2, 0.20, "bull", "late"),
            robustness_row(3, 0.05, "bear", "early"),
            robustness_row(4, 0.10, "bear", "late"),
        )

        result = regime_subperiod_robustness(
            rows,
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertAlmostEqual(result.overall_mean or 0, 0.1125)
        self.assertEqual(result.regime_sign_consistency_ratio, 1.0)
        self.assertEqual(result.subperiod_sign_consistency_ratio, 1.0)
        self.assertAlmostEqual(result.slice("regime", "bull").mean or 0, 0.15)
        self.assertAlmostEqual(result.slice("regime", "bear").mean or 0, 0.075)
        self.assertAlmostEqual(result.slice("subperiod", "early").mean or 0, 0.075)
        self.assertAlmostEqual(result.slice("subperiod", "late").mean or 0, 0.15)
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            self.assertAlmostEqual(
                result.overall_mean or 0, float(np.mean([0.10, 0.20, 0.05, 0.10]))
            )
            self.assertAlmostEqual(
                result.slice("regime", "bull").standard_deviation or 0,
                float(np.std([0.10, 0.20], ddof=1)),
            )

    def test_small_or_missing_slices_are_unavailable_and_block_overall_result(self) -> None:
        rows = (
            robustness_row(1, 0.10, "bull", "early"),
            robustness_row(2, None, "bull", "late", missing_reason="estimate missing"),
            robustness_row(3, 0.05, "bear", "early"),
        )

        result = regime_subperiod_robustness(
            rows,
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(result.overall_mean)
        self.assertTrue(
            any(value.status is StatisticStatus.UNAVAILABLE for value in result.regime_slices)
        )
        self.assertTrue(
            any(value.status is StatisticStatus.UNAVAILABLE for value in result.subperiod_slices)
        )
        self.assertTrue(result.unavailable_reason)

    def test_slice_artifacts_are_deterministic_when_input_order_changes(self) -> None:
        rows = (
            robustness_row(1, 0.10, "bull", "early"),
            robustness_row(2, 0.20, "bull", "late"),
            robustness_row(3, 0.05, "bear", "early"),
            robustness_row(4, 0.10, "bear", "late"),
        )

        forward = regime_subperiod_robustness(
            rows,
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        backward = regime_subperiod_robustness(
            tuple(reversed(rows)),
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(forward, backward)
        self.assertEqual(
            tuple(value.slice_id for value in forward.regime_slices),
            ("bear", "bull"),
        )


if __name__ == "__main__":
    unittest.main()
