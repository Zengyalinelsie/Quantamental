import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from a_share_platform.domain.factor_panel_statistics import (
    FamaMacBethObservation,
    FamaMacBethSpec,
)
from a_share_platform.domain.factor_statistics import (
    CorrelationKind,
    CorrelationSpec,
    CrossSectionObservation,
    HACNeweyWestSpec,
    StatisticsScientificStatus,
    TimeSeriesObservation,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.validation.statistical_crosscheck import (
    CrossCheckSpec,
    CrossCheckStatus,
    cross_check_fama_macbeth,
    cross_check_information_coefficient,
    cross_check_newey_west_mean,
)

BASE_TIME = datetime(2024, 1, 2, 9, 30, tzinfo=UTC)
CROSS_CHECK = CrossCheckSpec(
    absolute_tolerance=1e-12,
    relative_tolerance=1e-10,
    adapter_version="scipy-statsmodels-crosscheck:v1",
)


def cross_row(entity_id: str, score: float, outcome: float) -> CrossSectionObservation:
    return CrossSectionObservation(
        entity_id=entity_id,
        score=score,
        forward_return=outcome,
        score_version_id="feature:quality:v1",
        label_version_id="label:forward-return-20d:v1",
        data_mode=DataMode.STRICT_HISTORICAL,
        score_trust_state=DataTrustState.PIT_VERIFIED,
        label_trust_state=DataTrustState.PIT_VERIFIED,
        decision_time=BASE_TIME,
        score_available_at=BASE_TIME - timedelta(seconds=1),
        label_outcome_at=BASE_TIME + timedelta(days=20),
    )


def time_row(period: int, value: float) -> TimeSeriesObservation:
    return TimeSeriesObservation(
        period_id=f"period:{period}",
        value=value,
        statistic_version_id="rank-ic-series:v1",
        data_mode=DataMode.STRICT_HISTORICAL,
        trust_state=DataTrustState.PIT_VERIFIED,
        availability_enforced=True,
    )


def panel_row(
    period: int,
    entity_id: str,
    quality: float,
    value: float,
    outcome: float,
) -> FamaMacBethObservation:
    decision_time = BASE_TIME + timedelta(days=period * 30)
    return FamaMacBethObservation(
        period_id=f"period:{period}",
        entity_id=entity_id,
        forward_return=outcome,
        factor_values=(("quality", quality), ("value", value)),
        factor_version_ids=(
            ("quality", "feature:quality:v1"),
            ("value", "feature:value:v1"),
        ),
        label_version_id="label:forward-return-20d:v1",
        data_mode=DataMode.STRICT_HISTORICAL,
        factor_trust_state=DataTrustState.PIT_VERIFIED,
        label_trust_state=DataTrustState.PIT_VERIFIED,
        decision_time=decision_time,
        factor_available_at=decision_time - timedelta(seconds=1),
        label_outcome_at=decision_time + timedelta(days=20),
    )


def exact_period(
    period: int,
    intercept: float,
    quality_beta: float,
    value_beta: float,
) -> tuple[FamaMacBethObservation, ...]:
    factors = (("A", 0.0, 0.0), ("B", 1.0, 0.0), ("C", 0.0, 1.0), ("D", 1.0, 1.0))
    return tuple(
        panel_row(
            period,
            entity_id,
            quality,
            value,
            intercept + quality_beta * quality + value_beta * value,
        )
        for entity_id, quality, value in factors
    )


class IndependentStatisticalCrossCheckTest(unittest.TestCase):
    def test_scipy_cross_checks_pearson_and_tied_rank_ic_with_auditable_metadata(self) -> None:
        rows = tuple(
            cross_row(str(index), score, outcome)
            for index, (score, outcome) in enumerate(
                zip((1.0, 2.0, 2.0, 4.0, 5.0), (4.0, 1.0, 2.0, 3.0, 5.0)),
                start=1,
            )
        )

        for kind, formula, rank_version in (
            (CorrelationKind.PEARSON, "pearson-product-moment:v1", None),
            (
                CorrelationKind.SPEARMAN,
                "spearman-pearson-average-ranks:v1",
                "average-ties:v1",
            ),
        ):
            with self.subTest(kind=kind):
                report = cross_check_information_coefficient(
                    rows,
                    spec=CorrelationSpec(
                        kind=kind,
                        minimum_sample_size=5,
                        formula_version=formula,
                        rank_version=rank_version,
                    ),
                    cross_check_spec=CROSS_CHECK,
                    data_mode=DataMode.STRICT_HISTORICAL,
                )

                self.assertEqual(report.status, CrossCheckStatus.MATCHED)
                self.assertTrue(report.component("coefficient").within_tolerance)
                self.assertEqual(report.reference_libraries[0].name, "scipy")
                self.assertTrue(report.reference_libraries[0].version)
                self.assertEqual(len(report.input_digest), 64)
                self.assertEqual(report.absolute_tolerance, 1e-12)
                self.assertIn(formula, report.primary_formula_versions)
                self.assertEqual(
                    report.scientific_status,
                    StatisticsScientificStatus.NOT_EVALUATED,
                )
                self.assertTrue(any("scientific validity" in item for item in report.warnings))

    def test_statsmodels_cross_checks_newey_west_mean_without_small_sample_correction(self) -> None:
        rows = tuple(time_row(index, value) for index, value in enumerate((1, 2, 3, 4), 1))

        report = cross_check_newey_west_mean(
            rows,
            spec=HACNeweyWestSpec(
                max_lag=1,
                minimum_sample_size=4,
                formula_version="newey-west-bartlett-mean:v1",
            ),
            cross_check_spec=CROSS_CHECK,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(report.status, CrossCheckStatus.MATCHED)
        self.assertEqual(
            tuple(component.name for component in report.components),
            ("mean", "long_run_variance", "standard_error", "t_statistic"),
        )
        self.assertTrue(all(component.within_tolerance for component in report.components))
        self.assertEqual(report.reference_libraries[0].name, "statsmodels")
        self.assertIn("use_correction=False", report.reference_method)

    def test_statsmodels_cross_checks_fama_macbeth_period_ols_and_aggregate(self) -> None:
        rows = tuple(
            row
            for period, coefficients in enumerate(
                ((0.01, 0.02, 0.03), (0.02, 0.04, 0.01), (0.00, 0.03, 0.02)),
                start=1,
            )
            for row in exact_period(period, *coefficients)
        )

        report = cross_check_fama_macbeth(
            rows,
            spec=FamaMacBethSpec(
                factor_names=("quality", "value"),
                include_intercept=True,
                minimum_cross_section_size=4,
                minimum_period_count=3,
                rank_tolerance=1e-12,
                formula_version="cross-sectional-ols-then-time-mean:v1",
                standard_error_version="sample-sd-over-sqrt-periods:v1",
            ),
            cross_check_spec=CROSS_CHECK,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(report.status, CrossCheckStatus.MATCHED)
        self.assertTrue(report.component("aggregate.quality.mean").within_tolerance)
        self.assertTrue(report.component("aggregate.quality.standard_error").within_tolerance)
        self.assertTrue(report.component("period:1.quality").within_tolerance)
        self.assertIn("OLS per period", report.reference_method)

    def test_missing_optional_reference_dependency_is_explicitly_unavailable(self) -> None:
        rows = tuple(
            cross_row(str(index), score, outcome)
            for index, (score, outcome) in enumerate(
                zip((1.0, 2.0, 3.0), (3.0, 2.0, 1.0)),
                start=1,
            )
        )
        real_import = __import__("importlib").import_module

        def missing_scipy(name: str):
            if name.startswith("scipy"):
                raise ModuleNotFoundError("No module named 'scipy'", name="scipy")
            return real_import(name)

        with patch(
            "a_share_platform.validation.statistical_crosscheck.importlib.import_module",
            side_effect=missing_scipy,
        ):
            report = cross_check_information_coefficient(
                rows,
                spec=CorrelationSpec(
                    kind=CorrelationKind.PEARSON,
                    minimum_sample_size=3,
                    formula_version="pearson-product-moment:v1",
                    rank_version=None,
                ),
                cross_check_spec=CROSS_CHECK,
                data_mode=DataMode.STRICT_HISTORICAL,
            )

        self.assertEqual(report.status, CrossCheckStatus.UNAVAILABLE)
        self.assertEqual(report.components, ())
        self.assertIn("optional dependency scipy", report.unavailable_reason or "")
        self.assertEqual(report.reference_libraries, ())

    def test_reference_disagreement_is_a_mismatch_not_a_pass(self) -> None:
        rows = tuple(
            cross_row(str(index), score, outcome)
            for index, (score, outcome) in enumerate(
                zip((1.0, 2.0, 3.0), (1.0, 2.0, 3.0)),
                start=1,
            )
        )
        fake_result = SimpleNamespace(statistic=-1.0)
        fake_scipy = SimpleNamespace(__version__="independent-test-version")
        fake_stats = SimpleNamespace(pearsonr=lambda _left, _right: fake_result)

        with patch(
            "a_share_platform.validation.statistical_crosscheck._load_reference",
            return_value=(fake_scipy, fake_stats),
        ):
            report = cross_check_information_coefficient(
                rows,
                spec=CorrelationSpec(
                    kind=CorrelationKind.PEARSON,
                    minimum_sample_size=3,
                    formula_version="pearson-product-moment:v1",
                    rank_version=None,
                ),
                cross_check_spec=CROSS_CHECK,
                data_mode=DataMode.STRICT_HISTORICAL,
            )

        self.assertEqual(report.status, CrossCheckStatus.MISMATCH)
        self.assertFalse(report.component("coefficient").within_tolerance)
        self.assertGreater(report.component("coefficient").absolute_error, 1.0)


if __name__ == "__main__":
    unittest.main()
