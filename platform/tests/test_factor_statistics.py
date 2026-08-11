import importlib.util
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from a_share_platform.domain.factor_statistics import (
    BlockBootstrapSpec,
    CorrelationKind,
    CorrelationSpec,
    CrossSectionObservation,
    HACNeweyWestSpec,
    StatisticStatus,
    TimeSeriesObservation,
    block_bootstrap_mean_ci,
    information_coefficient,
    newey_west_mean_test,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode


def cross_observation(
    entity_id: str,
    score: float | None,
    forward_return: float | None,
    *,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
    missing_reason: str | None = None,
) -> CrossSectionObservation:
    decision_time = datetime(2024, 12, 31, 9, 30, tzinfo=UTC)
    return CrossSectionObservation(
        entity_id=entity_id,
        score=score,
        forward_return=forward_return,
        score_version_id="feature:improvement:v1",
        label_version_id="label:forward-return:v1",
        data_mode=data_mode,
        score_trust_state=trust_state,
        label_trust_state=trust_state,
        missing_reason=missing_reason,
        decision_time=decision_time,
        score_available_at=decision_time - timedelta(seconds=1),
        label_outcome_at=decision_time + timedelta(days=30),
    )


def time_observation(
    index: int,
    value: float | None,
    *,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
    missing_reason: str | None = None,
) -> TimeSeriesObservation:
    return TimeSeriesObservation(
        period_id=f"2024-{index:02d}",
        value=value,
        statistic_version_id="daily-rank-ic:v1",
        data_mode=data_mode,
        trust_state=trust_state,
        missing_reason=missing_reason,
        availability_enforced=True,
    )


class InformationCoefficientTest(unittest.TestCase):
    def test_pearson_and_spearman_match_hand_calculation_and_numpy(self) -> None:
        rows = tuple(
            cross_observation(str(index), score, outcome)
            for index, (score, outcome) in enumerate(
                zip((1.0, 2.0, 3.0, 4.0, 5.0), (2.0, 1.0, 4.0, 3.0, 5.0)),
                start=1,
            )
        )
        pearson = information_coefficient(
            rows,
            spec=CorrelationSpec(
                kind=CorrelationKind.PEARSON,
                minimum_sample_size=5,
                formula_version="pearson-product-moment:v1",
                rank_version=None,
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        spearman = information_coefficient(
            rows,
            spec=CorrelationSpec(
                kind=CorrelationKind.SPEARMAN,
                minimum_sample_size=5,
                formula_version="spearman-pearson-average-ranks:v1",
                rank_version="average-ties:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(pearson.status, StatisticStatus.QUANTIFIED)
        self.assertAlmostEqual(pearson.value or 0.0, 0.8)
        self.assertAlmostEqual(spearman.value or 0.0, 0.8)
        self.assertTrue(pearson.historical_eligible)
        if importlib.util.find_spec("numpy") is not None:
            import numpy as np

            expected = float(np.corrcoef([1, 2, 3, 4, 5], [2, 1, 4, 3, 5])[0, 1])
            self.assertAlmostEqual(pearson.value or 0.0, expected, places=12)
            self.assertAlmostEqual(spearman.value or 0.0, expected, places=12)

    def test_spearman_uses_average_ranks_for_ties(self) -> None:
        rows = tuple(
            cross_observation(str(index), score, outcome)
            for index, (score, outcome) in enumerate(
                zip((1.0, 2.0, 2.0, 4.0), (4.0, 1.0, 2.0, 3.0)),
                start=1,
            )
        )
        result = information_coefficient(
            rows,
            spec=CorrelationSpec(
                kind=CorrelationKind.SPEARMAN,
                minimum_sample_size=4,
                formula_version="spearman-pearson-average-ranks:v1",
                rank_version="average-ties:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertAlmostEqual(result.value or 0.0, -0.31622776601683794, places=12)

    def test_missing_pairs_are_explicit_and_too_few_is_unavailable(self) -> None:
        rows = (
            cross_observation("1", 1.0, 1.0),
            cross_observation("2", None, 2.0, missing_reason="score missing"),
            cross_observation("3", 3.0, 3.0),
        )
        result = information_coefficient(
            rows,
            spec=CorrelationSpec(
                kind=CorrelationKind.PEARSON,
                minimum_sample_size=3,
                formula_version="pearson-product-moment:v1",
                rank_version=None,
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertEqual(result.sample_size, 2)
        self.assertEqual(result.missing_count, 1)
        self.assertIn("minimum_sample_size=3", result.unavailable_reason or "")

    def test_current_scores_cannot_be_relabelled_as_historical_ic(self) -> None:
        current_rows = tuple(
            cross_observation(
                str(index),
                float(index),
                float(index),
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )
            for index in range(1, 4)
        )
        spec = CorrelationSpec(
            kind=CorrelationKind.PEARSON,
            minimum_sample_size=3,
            formula_version="pearson-product-moment:v1",
            rank_version=None,
        )

        current = information_coefficient(
            current_rows,
            spec=spec,
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertFalse(current.historical_eligible)
        self.assertTrue(any("current" in warning for warning in current.warnings))
        with self.assertRaisesRegex(PermissionError, "pit_verified|relabel"):
            information_coefficient(
                current_rows,
                spec=spec,
                data_mode=DataMode.STRICT_HISTORICAL,
            )

        strict = cross_observation("strict", 1.0, 1.0)
        with self.assertRaisesRegex(ValueError, "score available_at cannot exceed decision_time"):
            replace(strict, score_available_at=strict.decision_time + timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "label outcome must follow decision_time"):
            replace(strict, label_outcome_at=strict.decision_time)
        with self.assertRaisesRegex(ValueError, "one decision_time"):
            information_coefficient(
                (
                    cross_observation("one", 1.0, 1.0),
                    replace(
                        cross_observation("two", 2.0, 2.0),
                        decision_time=strict.decision_time + timedelta(days=1),
                        label_outcome_at=strict.label_outcome_at + timedelta(days=1),
                    ),
                    cross_observation("three", 3.0, 3.0),
                ),
                spec=spec,
                data_mode=DataMode.STRICT_HISTORICAL,
            )


class HACNeweyWestTest(unittest.TestCase):
    def test_lag_one_mean_statistic_matches_hand_calculation(self) -> None:
        rows = tuple(time_observation(index, value) for index, value in enumerate((1, 2, 3, 4), 1))
        result = newey_west_mean_test(
            rows,
            spec=HACNeweyWestSpec(
                max_lag=1,
                minimum_sample_size=4,
                formula_version="newey-west-bartlett-mean:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.QUANTIFIED)
        self.assertAlmostEqual(result.mean or 0.0, 2.5)
        self.assertAlmostEqual(result.long_run_variance or 0.0, 1.5625)
        self.assertAlmostEqual(result.standard_error or 0.0, 0.625)
        self.assertAlmostEqual(result.t_statistic or 0.0, 4.0)

    def test_missing_time_point_and_minimum_sample_fail_closed(self) -> None:
        rows = (
            time_observation(1, 0.1),
            time_observation(2, None, missing_reason="IC unavailable"),
            time_observation(3, 0.2),
        )
        result = newey_west_mean_test(
            rows,
            spec=HACNeweyWestSpec(
                max_lag=1,
                minimum_sample_size=3,
                formula_version="newey-west-bartlett-mean:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, StatisticStatus.UNAVAILABLE)
        self.assertIsNone(result.t_statistic)
        self.assertIn("missing time-series", result.unavailable_reason or "")
        with self.assertRaisesRegex(ValueError, "minimum_sample_size"):
            HACNeweyWestSpec(
                max_lag=3,
                minimum_sample_size=4,
                formula_version="newey-west-bartlett-mean:v1",
            )
        with self.assertRaisesRegex(PermissionError, "availability"):
            replace(rows[0], availability_enforced=False)


class BlockBootstrapTest(unittest.TestCase):
    def test_seeded_circular_block_bootstrap_is_reproducible(self) -> None:
        rows = tuple(
            time_observation(index, value)
            for index, value in enumerate((1.0, 2.0, 3.0, 4.0, 5.0), 1)
        )
        spec = BlockBootstrapSpec(
            block_size=2,
            resamples=1000,
            confidence_level=0.90,
            seed=17,
            minimum_sample_size=5,
            formula_version="circular-block-bootstrap-mean-linear-quantile:v1",
        )

        first = block_bootstrap_mean_ci(
            rows,
            spec=spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        repeated = block_bootstrap_mean_ci(
            rows,
            spec=spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(first, repeated)
        self.assertEqual(first.status, StatisticStatus.QUANTIFIED)
        self.assertEqual(first.seed, 17)
        self.assertEqual(first.block_size, 2)
        self.assertAlmostEqual(first.sample_mean or 0.0, 3.0)
        self.assertLess(first.lower_bound or 0.0, 3.0)
        self.assertGreater(first.upper_bound or 0.0, 3.0)

    def test_block_size_missing_and_current_context_are_explicit(self) -> None:
        strict_rows = tuple(time_observation(index, float(index)) for index in range(1, 5))
        too_large = block_bootstrap_mean_ci(
            strict_rows,
            spec=BlockBootstrapSpec(
                block_size=5,
                resamples=100,
                confidence_level=0.95,
                seed=1,
                minimum_sample_size=4,
                formula_version="circular-block-bootstrap-mean-linear-quantile:v1",
            ),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        self.assertEqual(too_large.status, StatisticStatus.UNAVAILABLE)
        self.assertIn("block_size", too_large.unavailable_reason or "")

        current_rows = tuple(
            replace(
                value,
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )
            for value in strict_rows
        )
        current = block_bootstrap_mean_ci(
            current_rows,
            spec=BlockBootstrapSpec(
                block_size=2,
                resamples=100,
                confidence_level=0.95,
                seed=9,
                minimum_sample_size=4,
                formula_version="circular-block-bootstrap-mean-linear-quantile:v1",
            ),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertFalse(current.historical_eligible)


if __name__ == "__main__":
    unittest.main()
