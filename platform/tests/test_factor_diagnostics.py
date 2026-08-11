import importlib.util
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from a_share_platform.domain.factor_diagnostics import (
    CoverageObservation,
    CoverageSpec,
    DecayObservation,
    DecaySpec,
    QuantilePortfolioSpec,
    TurnoverObservation,
    TurnoverSpec,
    factor_coverage,
    factor_decay,
    portfolio_turnover,
    quantile_portfolios,
)
from a_share_platform.domain.factor_statistics import (
    CrossSectionObservation,
    StatisticStatus,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

DECISION_TIME = datetime(2024, 12, 31, 9, 30, tzinfo=UTC)
AVAILABLE_AT = DECISION_TIME - timedelta(seconds=1)


def cross_row(
    index: int,
    score: float | None,
    forward_return: float | None,
    *,
    missing_reason: str | None = None,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
) -> CrossSectionObservation:
    return CrossSectionObservation(
        entity_id=f"security:{index:02d}",
        score=score,
        forward_return=forward_return,
        score_version_id="feature:quality:v1",
        label_version_id="label:forward-return-20d:v1",
        data_mode=data_mode,
        score_trust_state=trust_state,
        label_trust_state=trust_state,
        decision_time=DECISION_TIME,
        score_available_at=AVAILABLE_AT,
        label_outcome_at=DECISION_TIME + timedelta(days=30),
        missing_reason=missing_reason,
    )


def decay_row(
    horizon: int,
    value: float | None,
    *,
    missing_reason: str | None = None,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
) -> DecayObservation:
    return DecayObservation(
        horizon_sessions=horizon,
        correlation=value,
        statistic_version_id="rank-ic:quality:v1",
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=DECISION_TIME,
        available_at=AVAILABLE_AT,
        missing_reason=missing_reason,
    )


def holding(
    period_id: str,
    entity_id: str,
    weight: float | None,
    *,
    missing_reason: str | None = None,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
) -> TurnoverObservation:
    return TurnoverObservation(
        period_id=period_id,
        entity_id=entity_id,
        weight=weight,
        portfolio_version_id="portfolio-policy:quantile-long:v1",
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=DECISION_TIME,
        available_at=AVAILABLE_AT,
        missing_reason=missing_reason,
    )


def coverage_row(
    index: int,
    *,
    eligible: bool,
    score: float | None,
    missing_reason: str | None = None,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
) -> CoverageObservation:
    return CoverageObservation(
        entity_id=f"security:{index:02d}",
        eligible=eligible,
        score=score,
        universe_version_id="universe:csi500:2024-12-31:v1",
        score_version_id="feature:quality:v1",
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=DECISION_TIME,
        available_at=AVAILABLE_AT,
        missing_reason=missing_reason,
    )


class QuantilePortfolioDiagnosticsTest(unittest.TestCase):
    def test_equal_count_quantiles_and_monotonicity_match_hand_math_and_numpy(
        self,
    ) -> None:
        rows = tuple(cross_row(index, float(index), index / 100) for index in range(1, 11))
        result = quantile_portfolios(
            rows,
            spec=QuantilePortfolioSpec(
                quantile_count=5,
                minimum_sample_size=10,
                formula_version="equal-count-mean-return:v1",
                tie_break_version="score-then-entity-id:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(
            tuple(round(value.mean_return or 0, 3) for value in result.quantiles),
            (0.015, 0.035, 0.055, 0.075, 0.095),
        )
        self.assertTrue(result.monotonic)
        self.assertEqual(result.monotonicity_ratio, 1.0)
        self.assertAlmostEqual(result.top_minus_bottom or 0, 0.08)
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            expected = np.asarray([index / 100 for index in range(1, 11)]).reshape(5, 2)
            np.testing.assert_allclose(
                [value.mean_return for value in result.quantiles],
                expected.mean(axis=1),
                rtol=0,
                atol=1e-12,
            )

    def test_insufficient_complete_sample_is_unavailable_and_not_zero(self) -> None:
        rows = (
            cross_row(1, 1.0, 0.01),
            cross_row(2, 2.0, None, missing_reason="label is missing"),
            cross_row(3, 3.0, 0.03),
        )

        result = quantile_portfolios(
            rows,
            spec=QuantilePortfolioSpec(
                quantile_count=2,
                minimum_sample_size=3,
                formula_version="equal-count-mean-return:v1",
                tie_break_version="score-then-entity-id:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        self.assertEqual(result.quantiles, ())
        self.assertIsNone(result.top_minus_bottom)
        self.assertEqual(result.missing_count, 1)
        self.assertTrue(result.unavailable_reason)


class DecayTurnoverCoverageDiagnosticsTest(unittest.TestCase):
    def test_decay_curve_and_half_life_match_hand_math_and_numpy(self) -> None:
        rows = tuple(
            decay_row(horizon, value)
            for horizon, value in ((1, 0.12), (5, 0.08), (10, 0.06), (20, 0.03))
        )
        result = factor_decay(
            rows,
            spec=DecaySpec(
                minimum_horizons=4,
                formula_version="absolute-correlation-relative-to-first:v1",
                half_life_fraction=0.5,
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(result.half_life_sessions, 10)
        expected = (1.0, 2 / 3, 0.5, 0.25)
        for actual, target in zip(result.points, expected):
            self.assertAlmostEqual(actual.normalized_strength or 0, target)
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            np.testing.assert_allclose(
                [value.normalized_strength for value in result.points],
                np.abs(np.asarray([0.12, 0.08, 0.06, 0.03])) / 0.12,
                rtol=0,
                atol=1e-12,
            )

    def test_one_way_turnover_matches_union_weight_hand_math_and_numpy(self) -> None:
        rows = (
            holding("2024-12-31", "A", 0.6),
            holding("2024-12-31", "B", 0.4),
            holding("2025-01-31", "A", 0.3),
            holding("2025-01-31", "B", 0.3),
            holding("2025-01-31", "C", 0.4),
        )
        result = portfolio_turnover(
            rows,
            spec=TurnoverSpec(
                minimum_positions_per_period=2,
                weight_sum_tolerance=1e-12,
                formula_version="one-way-half-l1-union:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertAlmostEqual(result.value or 0, 0.4)
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            old = np.asarray([0.6, 0.4, 0.0])
            new = np.asarray([0.3, 0.3, 0.4])
            self.assertAlmostEqual(result.value or 0, float(0.5 * np.abs(new - old).sum()))

    def test_coverage_counts_only_eligible_quantified_scores(self) -> None:
        rows = (
            coverage_row(1, eligible=True, score=1.0),
            coverage_row(2, eligible=True, score=2.0),
            coverage_row(
                3,
                eligible=True,
                score=None,
                missing_reason="required financial feature is missing",
            ),
            coverage_row(4, eligible=True, score=4.0),
            coverage_row(
                5,
                eligible=False,
                score=None,
                missing_reason="outside research universe",
            ),
        )
        result = factor_coverage(
            rows,
            spec=CoverageSpec(
                minimum_eligible_count=4,
                minimum_coverage_ratio=0.8,
                formula_version="eligible-quantified-share:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(result.eligible_count, 4)
        self.assertEqual(result.quantified_count, 3)
        self.assertEqual(result.missing_count, 1)
        self.assertEqual(result.value, 0.75)
        self.assertFalse(result.meets_minimum)

    def test_missing_weight_and_too_small_coverage_are_unavailable_not_zero(self) -> None:
        turnover = portfolio_turnover(
            (
                holding("old", "A", 0.5),
                holding("old", "B", 0.5),
                holding("new", "A", None, missing_reason="weight calculation failed"),
                holding("new", "B", 1.0),
            ),
            spec=TurnoverSpec(
                minimum_positions_per_period=2,
                weight_sum_tolerance=1e-12,
                formula_version="one-way-half-l1-union:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        coverage = factor_coverage(
            (coverage_row(1, eligible=True, score=1.0),),
            spec=CoverageSpec(
                minimum_eligible_count=2,
                minimum_coverage_ratio=0.5,
                formula_version="eligible-quantified-share:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(turnover.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(turnover.value)
        self.assertEqual(coverage.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(coverage.value)

    def test_current_cannot_be_relabelled_and_strict_clock_fails_closed(self) -> None:
        current = coverage_row(
            1,
            eligible=True,
            score=1.0,
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
        )
        with self.assertRaisesRegex(PermissionError, "relabelled|pit_verified"):
            factor_coverage(
                (current,),
                spec=CoverageSpec(
                    minimum_eligible_count=1,
                    minimum_coverage_ratio=1.0,
                    formula_version="eligible-quantified-share:v1",
                ),
                data_mode=DataMode.STRICT_HISTORICAL,
            )
        with self.assertRaisesRegex(ValueError, "available_at cannot exceed decision_time"):
            replace(current, available_at=DECISION_TIME + timedelta(seconds=1))


if __name__ == "__main__":
    unittest.main()
