import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext

from a_share_platform.domain.feature_transforms import (
    CrossSectionRow,
    TransformStatus,
    execute_neutralization,
    execute_standardization,
    execute_winsorization,
)
from a_share_platform.domain.features import (
    FeatureCalculationStatus,
    NeutralizationExposure,
    NeutralizationSpec,
    StandardizationSpec,
    WinsorizationSpec,
)


def row(
    entity_id: str,
    value: str | None,
    *,
    industry: str | None = None,
    size: str | None = None,
) -> CrossSectionRow:
    return CrossSectionRow(
        entity_id=entity_id,
        value=None if value is None else Decimal(value),
        industry_code=industry,
        size_exposure=None if size is None else Decimal(size),
    )


def winsor_spec(**overrides: str) -> WinsorizationSpec:
    parameters = {
        "interpolation": "linear-rank-n-minus-one-v1",
        "lower": "0.25",
        "minimum_observations": "4",
        "upper": "0.75",
    }
    parameters.update(overrides)
    return WinsorizationSpec(
        method="cross-sectional-quantile",
        version="winsor:v1",
        parameters=tuple(sorted(parameters.items())),
    )


def standardization_spec(**overrides: str) -> StandardizationSpec:
    parameters = {"ddof": "0", "minimum_observations": "4"}
    parameters.update(overrides)
    return StandardizationSpec(
        method="cross-sectional-zscore",
        version="standardize:v1",
        parameters=tuple(sorted(parameters.items())),
    )


def neutralization_spec(**overrides: str) -> NeutralizationSpec:
    parameters = {
        "industry_baseline": "lexicographically-first",
        "minimum_observations": "6",
        "size_transform": "identity",
    }
    parameters.update(overrides)
    return NeutralizationSpec(
        method="cross-sectional-linear-residual",
        version="neutralize:v1",
        exposures=(NeutralizationExposure.INDUSTRY, NeutralizationExposure.SIZE),
        parameters=tuple(sorted(parameters.items())),
    )


def regression_rows() -> tuple[CrossSectionRow, ...]:
    # y = 10 + 5 * industry_B + 2 * size + residual, with X' residual = 0.
    return (
        row("A1", "13", industry="A", size="1"),
        row("A2", "12", industry="A", size="2"),
        row("A3", "17", industry="A", size="3"),
        row("B1", "16", industry="B", size="1"),
        row("B2", "21", industry="B", size="2"),
        row("B3", "20", industry="B", size="3"),
    )


class WinsorizationTest(unittest.TestCase):
    def test_quantiles_use_deterministic_n_minus_one_linear_interpolation(self) -> None:
        result = execute_winsorization(
            (
                row("one", "1"),
                row("two", "2"),
                row("three", "3"),
                row("outlier", "100"),
            ),
            winsor_spec(),
        )

        self.assertEqual(result.status, TransformStatus.QUANTIFIED)
        self.assertEqual(result.lower_bound, Decimal("1.75"))
        self.assertEqual(result.upper_bound, Decimal("27.25"))
        self.assertEqual(
            tuple(item.value for item in result.values),
            (Decimal("1.75"), Decimal(2), Decimal(3), Decimal("27.25")),
        )
        self.assertEqual(result.method, "cross-sectional-quantile")
        self.assertEqual(result.version, "winsor:v1")

    def test_missing_value_is_excluded_and_remains_unavailable_not_zero(self) -> None:
        result = execute_winsorization(
            (
                row("missing", None),
                row("one", "1"),
                row("two", "2"),
                row("three", "3"),
                row("four", "4"),
            ),
            winsor_spec(),
        )

        self.assertEqual(result.sample_size, 4)
        self.assertEqual(result.values[0].status, FeatureCalculationStatus.UNAVAILABLE)
        self.assertIsNone(result.values[0].value)
        self.assertEqual(result.values[0].reason, "input value is missing")

    def test_unknown_method_parameter_and_interpolation_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported winsorization method"):
            execute_winsorization(
                (row("one", "1"),),
                replace(winsor_spec(), method="vendor-default"),
            )
        with self.assertRaisesRegex(ValueError, "unknown winsorization parameters"):
            execute_winsorization(
                (row("one", "1"),),
                WinsorizationSpec(
                    method="cross-sectional-quantile",
                    version="winsor:v1",
                    parameters=(*winsor_spec().parameters, ("vendor_default", "true")),
                ),
            )
        with self.assertRaisesRegex(ValueError, "unsupported quantile interpolation"):
            execute_winsorization(
                (row("one", "1"),),
                winsor_spec(interpolation="nearest"),
            )

    def test_small_sample_is_explicitly_unavailable(self) -> None:
        result = execute_winsorization(
            (row("one", "1"), row("two", "2"), row("three", "3")),
            winsor_spec(),
        )

        self.assertEqual(result.status, TransformStatus.UNAVAILABLE)
        self.assertEqual(result.sample_size, 3)
        self.assertIn("required 4, observed 3", result.reason or "")
        self.assertTrue(all(item.value is None for item in result.values))


class StandardizationTest(unittest.TestCase):
    def test_population_zscore_is_decimal_and_deterministic(self) -> None:
        result = execute_standardization(
            (
                row("low-1", "1"),
                row("low-2", "1"),
                row("high-1", "3"),
                row("high-2", "3"),
            ),
            standardization_spec(),
        )

        self.assertEqual(result.status, TransformStatus.QUANTIFIED)
        self.assertEqual(result.mean, Decimal(2))
        self.assertEqual(result.standard_deviation, Decimal(1))
        self.assertEqual(
            tuple(item.value for item in result.values),
            (Decimal(-1), Decimal(-1), Decimal(1), Decimal(1)),
        )

    def test_ddof_one_is_consumed_from_the_versioned_spec(self) -> None:
        result = execute_standardization(
            (row("one", "1"), row("two", "2"), row("three", "3")),
            standardization_spec(ddof="1", minimum_observations="3"),
        )

        self.assertEqual(result.mean, Decimal(2))
        self.assertEqual(result.standard_deviation, Decimal(1))
        self.assertEqual(
            tuple(item.value for item in result.values),
            (Decimal(-1), Decimal(0), Decimal(1)),
        )

    def test_constant_column_and_small_sample_are_unavailable(self) -> None:
        constant = execute_standardization(
            tuple(row(str(index), "2") for index in range(4)),
            standardization_spec(),
        )
        small = execute_standardization(
            (row("one", "1"), row("two", "2")),
            standardization_spec(),
        )

        self.assertEqual(constant.status, TransformStatus.UNAVAILABLE)
        self.assertIn("zero standard deviation", constant.reason or "")
        self.assertEqual(small.status, TransformStatus.UNAVAILABLE)
        self.assertTrue(all(item.value is None for item in constant.values))

    def test_unknown_parameters_and_invalid_ddof_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown standardization parameters"):
            execute_standardization(
                (row("one", "1"),),
                StandardizationSpec(
                    method="cross-sectional-zscore",
                    version="standardize:v1",
                    parameters=(("ddof", "0"), ("epsilon", "0.001"), ("minimum_observations", "1")),
                ),
            )
        with self.assertRaisesRegex(ValueError, "ddof"):
            execute_standardization(
                (row("one", "1"),),
                standardization_spec(ddof="1.5"),
            )

    def test_execution_does_not_depend_on_the_process_decimal_context(self) -> None:
        values = (row("one", "1"), row("two", "2"), row("four", "4"), row("eight", "8"))
        with localcontext() as context:
            context.prec = 6
            low_precision_caller = execute_standardization(
                values, standardization_spec()
            )
        with localcontext() as context:
            context.prec = 28
            ordinary_caller = execute_standardization(values, standardization_spec())

        self.assertEqual(
            low_precision_caller.standard_deviation,
            ordinary_caller.standard_deviation,
        )
        self.assertEqual(low_precision_caller.values, ordinary_caller.values)

    def test_standardization_accumulation_is_independent_of_input_order(self) -> None:
        raw_values = (
            "-2.58054E+25",
            "8.01384E+50",
            "-6.61971E+50",
            "4.99781E+50",
            "3.73448E+60",
            "-4.75918E+50",
            "-4.14680E+50",
            "5.0340E+59",
        )
        rows = tuple(row(f"e{index}", value) for index, value in enumerate(raw_values))

        forward = execute_standardization(rows, standardization_spec())
        reverse = execute_standardization(tuple(reversed(rows)), standardization_spec())

        self.assertEqual(forward.mean, reverse.mean)
        self.assertEqual(forward.standard_deviation, reverse.standard_deviation)
        self.assertEqual(
            {item.entity_id: item.value for item in forward.values},
            {item.entity_id: item.value for item in reverse.values},
        )


class NeutralizationTest(unittest.TestCase):
    def test_ols_uses_lexicographically_first_industry_as_omitted_baseline(self) -> None:
        result = execute_neutralization(regression_rows(), neutralization_spec())

        self.assertEqual(result.status, TransformStatus.QUANTIFIED)
        self.assertEqual(result.industry_baseline, "A")
        self.assertEqual(
            tuple(name for name, _ in result.coefficients),
            ("intercept", "industry:B", "size"),
        )
        for (_, actual), expected in zip(
            result.coefficients,
            (Decimal(10), Decimal(5), Decimal(2)),
            strict=True,
        ):
            self.assertAlmostEqual(actual, expected, places=40)
        for item, expected in zip(
            result.values,
            (Decimal(1), Decimal(-2), Decimal(1), Decimal(-1), Decimal(2), Decimal(-1)),
            strict=True,
        ):
            assert item.value is not None
            self.assertAlmostEqual(item.value, expected, places=40)

    def test_input_order_does_not_change_baseline_or_entity_residuals(self) -> None:
        forward = execute_neutralization(regression_rows(), neutralization_spec())
        reverse = execute_neutralization(
            tuple(reversed(regression_rows())), neutralization_spec()
        )

        self.assertEqual(forward.industry_baseline, reverse.industry_baseline)
        self.assertEqual(
            {item.entity_id: item.value for item in forward.values},
            {item.entity_id: item.value for item in reverse.values},
        )

    def test_decimal_accumulation_order_is_canonical_for_extreme_scales(self) -> None:
        rows = (
            row("e0", "2.6962E+24", industry="A", size="7.68361E-15"),
            row("e1", "-9.08800E+50", industry="A", size="3.23517E+50"),
            row("e2", "-646432", industry="A", size="526636"),
            row("e3", "6.15905E-15", industry="A", size="209209"),
            row("e4", "7.7458E+49", industry="B", size="3.60528E+25"),
            row("e5", "9.07895E+50", industry="B", size="2.82360E-15"),
            row("e6", "6.43445E+50", industry="B", size="898577"),
            row("e7", "6.30321E+60", industry="B", size="588627"),
        )
        spec = neutralization_spec(minimum_observations="8")

        forward = execute_neutralization(rows, spec)
        reverse = execute_neutralization(tuple(reversed(rows)), spec)

        self.assertEqual(forward.coefficients, reverse.coefficients)
        self.assertEqual(
            {item.entity_id: item.value for item in forward.values},
            {item.entity_id: item.value for item in reverse.values},
        )

    def test_missing_industry_or_size_remains_unavailable_and_is_not_imputed(self) -> None:
        rows = (*regression_rows(), row("missing-industry", "99", size="4"))
        result = execute_neutralization(rows, neutralization_spec())

        missing = result.values[-1]
        self.assertEqual(result.sample_size, 6)
        self.assertEqual(missing.status, FeatureCalculationStatus.UNAVAILABLE)
        self.assertIsNone(missing.value)
        self.assertEqual(missing.reason, "industry_code is missing")

    def test_singular_design_matrix_and_too_few_rows_are_unavailable(self) -> None:
        singular = execute_neutralization(
            tuple(
                row(
                    f"{industry}{index}",
                    str(index),
                    industry=industry,
                    size="1",
                )
                for industry in ("A", "B")
                for index in range(1, 4)
            ),
            neutralization_spec(),
        )
        small = execute_neutralization(
            regression_rows()[:2],
            neutralization_spec(minimum_observations="2"),
        )

        self.assertEqual(singular.status, TransformStatus.UNAVAILABLE)
        self.assertIn("singular", singular.reason or "")
        self.assertEqual(small.status, TransformStatus.UNAVAILABLE)
        self.assertIn("more observations than regressors", small.reason or "")

    def test_unknown_method_parameters_baseline_and_size_transform_fail_closed(self) -> None:
        invalid_specs = (
            (
                replace(neutralization_spec(), method="vendor-residual"),
                "unsupported neutralization method",
            ),
            (
                NeutralizationSpec(
                    method="cross-sectional-linear-residual",
                    version="neutralize:v1",
                    exposures=(
                        NeutralizationExposure.INDUSTRY,
                        NeutralizationExposure.SIZE,
                    ),
                    parameters=tuple(
                        sorted((*neutralization_spec().parameters, ("ridge", "0.1")))
                    ),
                ),
                "unknown neutralization parameters",
            ),
            (
                neutralization_spec(industry_baseline="largest-industry"),
                "unsupported industry baseline",
            ),
            (
                neutralization_spec(size_transform="log"),
                "unsupported size transform",
            ),
        )
        for invalid, message in invalid_specs:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                execute_neutralization(regression_rows(), invalid)

    def test_rows_and_results_are_immutable(self) -> None:
        value = row("one", "1", industry="A", size="1")
        result = execute_winsorization(
            (value, row("two", "2"), row("three", "3"), row("four", "4")),
            winsor_spec(),
        )

        with self.assertRaises(FrozenInstanceError):
            value.value = Decimal(2)  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.sample_size = 0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
