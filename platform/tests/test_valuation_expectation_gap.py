import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.features import FeaturePeriod
from a_share_platform.domain.industry_templates import IndustryTemplateId
from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import (
    ValuationComponentStatus,
    ValuationExpectationMetric,
    ValuationExpectationRangeInput,
    ValuationExpectationSource,
    ValuationExposures,
    ValuationInputProvenance,
    ValuationMetric,
    ValuationMetricInput,
    ValuationResultStatus,
    ValuationScientificStatus,
    valuation_expectation_gap_definition_v0,
)

HASH_A = "sha256:" + "a" * 64


def provenance(name: str) -> ValuationInputProvenance:
    return ValuationInputProvenance(
        dataset_version_id="dataset:valuation-inputs:2024q4:v1",
        method_id=f"method:{name}",
        method_version="v1",
        source_observation_ids=(f"observation:{name}:2024q4:v1",),
        content_hashes=(HASH_A,),
    )


def metric_input(
    metric: ValuationMetric,
    numerator: str | None,
    denominator: str | None,
    *,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    unavailable_reasons: tuple[str, ...] = (),
    decision_time: datetime | None = None,
    available_at: datetime | None = None,
) -> ValuationMetricInput:
    specifications = {
        ValuationMetric.EARNINGS_TO_PRICE: (
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.TTM,
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
        ),
        ValuationMetric.BOOK_TO_PRICE: (
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
        ),
        ValuationMetric.FREE_CASH_FLOW_YIELD: (
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.TTM,
            MetricUnit.CURRENCY_PER_SHARE,
            FeaturePeriod.INSTANT,
        ),
        ValuationMetric.ENTERPRISE_VALUE_TO_EBIT: (
            MetricUnit.CURRENCY,
            FeaturePeriod.INSTANT,
            MetricUnit.CURRENCY,
            FeaturePeriod.TTM,
        ),
    }
    numerator_unit, numerator_period, denominator_unit, denominator_period = specifications[metric]
    return ValuationMetricInput(
        metric=metric,
        numerator=None if numerator is None else Decimal(numerator),
        denominator=None if denominator is None else Decimal(denominator),
        numerator_unit=numerator_unit,
        numerator_period=numerator_period,
        denominator_unit=denominator_unit,
        denominator_period=denominator_period,
        currency="CNY",
        provenance=provenance(metric.value),
        data_mode=data_mode,
        trust_state=trust_state,
        unavailable_reasons=unavailable_reasons,
        decision_time=decision_time,
        latest_source_available_at=available_at,
    )


def expectation(
    source: ValuationExpectationSource,
    lower: str | None,
    upper: str | None,
    *,
    metric: ValuationExpectationMetric = ValuationExpectationMetric.GROWTH,
    data_mode: DataMode = DataMode.CURRENT_RESEARCH,
    trust_state: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    unavailable_reasons: tuple[str, ...] = (),
    decision_time: datetime | None = None,
    available_at: datetime | None = None,
) -> ValuationExpectationRangeInput:
    return ValuationExpectationRangeInput(
        source=source,
        expectation_metric=metric,
        lower=None if lower is None else Decimal(lower),
        upper=None if upper is None else Decimal(upper),
        unit=MetricUnit.RATIO,
        assumptions=(f"{source.value} assumptions:v1",),
        invalidation_conditions=(f"{source.value} method invalidation:v1",),
        provenance=provenance(source.value),
        data_mode=data_mode,
        trust_state=trust_state,
        unavailable_reasons=unavailable_reasons,
        decision_time=decision_time,
        latest_source_available_at=available_at,
    )


def exposures() -> ValuationExposures:
    return ValuationExposures(
        industry_code="C30",
        log_market_cap=Decimal("23.5"),
        beta=Decimal("1.1"),
    )


class ValuationExpectationGapV0Test(unittest.TestCase):
    def test_four_company_hand_calculations_are_interval_based(self) -> None:
        cases = (
            (
                "manufacturer-positive-gap",
                IndustryTemplateId.MANUFACTURING_CONSUMER,
                {
                    ValuationMetric.EARNINGS_TO_PRICE: ("5", "50"),
                    ValuationMetric.BOOK_TO_PRICE: ("20", "50"),
                    ValuationMetric.FREE_CASH_FLOW_YIELD: ("4", "50"),
                    ValuationMetric.ENTERPRISE_VALUE_TO_EBIT: ("120", "20"),
                },
                ("0.08", "0.10"),
                ("0.12", "0.15"),
                ValuationResultStatus.QUANTIFIED,
                (Decimal("0.02"), Decimal("0.07")),
            ),
            (
                "bank-industry-applicable",
                IndustryTemplateId.BANK,
                {
                    ValuationMetric.EARNINGS_TO_PRICE: ("2", "10"),
                    ValuationMetric.BOOK_TO_PRICE: ("8", "10"),
                },
                ("0.10", "0.12"),
                ("0.13", "0.16"),
                ValuationResultStatus.QUANTIFIED,
                (Decimal("0.01"), Decimal("0.06")),
            ),
            (
                "non-financial-negative-gap",
                IndustryTemplateId.NON_FINANCIAL_GENERAL,
                {
                    ValuationMetric.EARNINGS_TO_PRICE: ("3", "40"),
                    ValuationMetric.BOOK_TO_PRICE: ("12", "40"),
                    ValuationMetric.FREE_CASH_FLOW_YIELD: ("2", "40"),
                    ValuationMetric.ENTERPRISE_VALUE_TO_EBIT: ("100", "10"),
                },
                ("0.15", "0.18"),
                ("0.10", "0.12"),
                ValuationResultStatus.QUANTIFIED,
                (Decimal("-0.08"), Decimal("-0.03")),
            ),
            (
                "manufacturer-missing-fcf",
                IndustryTemplateId.MANUFACTURING_CONSUMER,
                {
                    ValuationMetric.EARNINGS_TO_PRICE: ("5", "50"),
                    ValuationMetric.BOOK_TO_PRICE: ("20", "50"),
                    ValuationMetric.FREE_CASH_FLOW_YIELD: (None, None),
                    ValuationMetric.ENTERPRISE_VALUE_TO_EBIT: ("120", "20"),
                },
                ("0.08", "0.10"),
                ("0.12", "0.15"),
                ValuationResultStatus.PARTIAL,
                (Decimal("0.02"), Decimal("0.07")),
            ),
        )

        for name, template_id, raw_metrics, implied, anchor, status, gap in cases:
            with self.subTest(company=name):
                definition = valuation_expectation_gap_definition_v0(template_id)
                values = {
                    metric: metric_input(
                        metric,
                        numerator,
                        denominator,
                        unavailable_reasons=("FCF is unavailable",) if numerator is None else (),
                    )
                    for metric, (numerator, denominator) in raw_metrics.items()
                }
                result = definition.calculate(
                    values,
                    market_implied=expectation(
                        ValuationExpectationSource.MARKET_IMPLIED,
                        *implied,
                        metric=(
                            ValuationExpectationMetric.RETURN_ON_EQUITY
                            if template_id is IndustryTemplateId.BANK
                            else ValuationExpectationMetric.GROWTH
                        ),
                    ),
                    fundamental_anchor=expectation(
                        ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
                        *anchor,
                        metric=(
                            ValuationExpectationMetric.RETURN_ON_EQUITY
                            if template_id is IndustryTemplateId.BANK
                            else ValuationExpectationMetric.GROWTH
                        ),
                    ),
                    exposures=exposures(),
                    data_mode=DataMode.CURRENT_RESEARCH,
                    currency="CNY",
                    comparable_set_version_id="comparable-set:industry:2024q4:v1",
                )

                self.assertEqual(result.status, status)
                self.assertEqual(
                    (result.gap_interval.lower, result.gap_interval.upper),  # type: ignore[union-attr]
                    gap,
                )
                self.assertFalse(hasattr(result, "target_price"))
                self.assertEqual(
                    result.scientific_status,
                    ValuationScientificStatus.NOT_EVALUATED,
                )

        manufacturer = valuation_expectation_gap_definition_v0(
            IndustryTemplateId.MANUFACTURING_CONSUMER
        )
        inputs = {
            metric: metric_input(metric, numerator, denominator)
            for metric, (numerator, denominator) in cases[0][2].items()
        }
        calculated = manufacturer.calculate(
            inputs,
            market_implied=expectation(
                ValuationExpectationSource.MARKET_IMPLIED,
                "0.08",
                "0.10",
            ),
            fundamental_anchor=expectation(
                ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
                "0.12",
                "0.15",
            ),
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
            currency="CNY",
            comparable_set_version_id="comparable-set:industry:2024q4:v1",
        )
        self.assertEqual(
            calculated.component(ValuationMetric.EARNINGS_TO_PRICE).value,
            Decimal("0.1"),
        )
        self.assertEqual(
            calculated.component(ValuationMetric.BOOK_TO_PRICE).value,
            Decimal("0.4"),
        )
        self.assertEqual(
            calculated.component(ValuationMetric.FREE_CASH_FLOW_YIELD).value,
            Decimal("0.08"),
        )
        self.assertEqual(
            calculated.component(ValuationMetric.ENTERPRISE_VALUE_TO_EBIT).value,
            Decimal(6),
        )

    def test_bank_marks_fcf_yield_and_ev_ebit_not_applicable(self) -> None:
        definition = valuation_expectation_gap_definition_v0(IndustryTemplateId.BANK)
        result = definition.calculate(
            {
                ValuationMetric.EARNINGS_TO_PRICE: metric_input(
                    ValuationMetric.EARNINGS_TO_PRICE, "2", "10"
                ),
                ValuationMetric.BOOK_TO_PRICE: metric_input(
                    ValuationMetric.BOOK_TO_PRICE, "8", "10"
                ),
            },
            market_implied=expectation(
                ValuationExpectationSource.MARKET_IMPLIED,
                "0.10",
                "0.12",
                metric=ValuationExpectationMetric.RETURN_ON_EQUITY,
            ),
            fundamental_anchor=expectation(
                ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
                "0.13",
                "0.16",
                metric=ValuationExpectationMetric.RETURN_ON_EQUITY,
            ),
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
            currency="CNY",
            comparable_set_version_id="comparable-set:bank:2024q4:v1",
        )

        for metric in (
            ValuationMetric.FREE_CASH_FLOW_YIELD,
            ValuationMetric.ENTERPRISE_VALUE_TO_EBIT,
        ):
            component = result.component(metric)
            self.assertEqual(component.status, ValuationComponentStatus.NOT_APPLICABLE)
            self.assertIsNone(component.value)
        self.assertIn("bank", result.assumptions[0].lower())

    def test_missing_expectation_range_is_unavailable_not_numeric_zero(self) -> None:
        definition = valuation_expectation_gap_definition_v0(
            IndustryTemplateId.NON_FINANCIAL_GENERAL
        )
        values = {
            metric: metric_input(metric, "1", "10") for metric in definition.applicable_metrics
        }
        result = definition.calculate(
            values,
            market_implied=expectation(
                ValuationExpectationSource.MARKET_IMPLIED,
                None,
                None,
                unavailable_reasons=("implied expectation inversion failed",),
            ),
            fundamental_anchor=expectation(
                ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
                "0.10",
                "0.12",
            ),
            exposures=exposures(),
            data_mode=DataMode.CURRENT_RESEARCH,
            currency="CNY",
            comparable_set_version_id="comparable-set:industry:2024q4:v1",
        )

        self.assertEqual(result.status, ValuationResultStatus.UNAVAILABLE)
        self.assertIsNone(result.gap_interval)
        self.assertTrue(result.unavailable_reasons)

    def test_current_cannot_be_relabelled_strict_and_strict_checks_every_clock(self) -> None:
        definition = valuation_expectation_gap_definition_v0(IndustryTemplateId.BANK)
        current_values = {
            ValuationMetric.EARNINGS_TO_PRICE: metric_input(
                ValuationMetric.EARNINGS_TO_PRICE, "2", "10"
            ),
            ValuationMetric.BOOK_TO_PRICE: metric_input(ValuationMetric.BOOK_TO_PRICE, "8", "10"),
        }
        current_implied = expectation(
            ValuationExpectationSource.MARKET_IMPLIED,
            "0.10",
            "0.12",
            metric=ValuationExpectationMetric.RETURN_ON_EQUITY,
        )
        current_anchor = expectation(
            ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
            "0.13",
            "0.16",
            metric=ValuationExpectationMetric.RETURN_ON_EQUITY,
        )
        with self.assertRaisesRegex(PermissionError, "relabelled|pit_verified"):
            definition.calculate(
                current_values,
                market_implied=current_implied,
                fundamental_anchor=current_anchor,
                exposures=exposures(),
                data_mode=DataMode.STRICT_HISTORICAL,
                currency="CNY",
                comparable_set_version_id="comparable-set:bank:2024q4:v1",
            )

        decision_time = datetime(2025, 1, 2, 9, 30, tzinfo=UTC)
        available_at = decision_time - timedelta(seconds=1)
        strict_values = {
            metric: replace(
                value,
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.PIT_VERIFIED,
                decision_time=decision_time,
                latest_source_available_at=available_at,
            )
            for metric, value in current_values.items()
        }
        strict_implied = replace(
            current_implied,
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
            decision_time=decision_time,
            latest_source_available_at=available_at,
        )
        strict_anchor = replace(
            current_anchor,
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
            decision_time=decision_time,
            latest_source_available_at=available_at,
        )
        strict = definition.calculate(
            strict_values,
            market_implied=strict_implied,
            fundamental_anchor=strict_anchor,
            exposures=exposures(),
            data_mode=DataMode.STRICT_HISTORICAL,
            currency="CNY",
            comparable_set_version_id="comparable-set:bank:2024q4:v1",
        )

        self.assertTrue(strict.historical_eligible)
        self.assertEqual(strict.decision_time, decision_time)
        self.assertLessEqual(strict.latest_input_available_at, decision_time)
        with self.assertRaisesRegex(ValueError, "available_at cannot exceed decision_time"):
            replace(
                next(iter(strict_values.values())),
                latest_source_available_at=decision_time + timedelta(seconds=1),
            )

    def test_units_periods_assumptions_currency_and_invalidation_are_explicit(self) -> None:
        valid = metric_input(ValuationMetric.EARNINGS_TO_PRICE, "2", "10")
        with self.assertRaisesRegex(ValueError, "period"):
            replace(valid, numerator_period=FeaturePeriod.INSTANT)
        with self.assertRaisesRegex(ValueError, "currency"):
            replace(valid, currency="")
        with self.assertRaisesRegex(ValueError, "invalidation"):
            replace(
                expectation(
                    ValuationExpectationSource.MARKET_IMPLIED,
                    "0.10",
                    "0.12",
                ),
                invalidation_conditions=(),
            )


if __name__ == "__main__":
    unittest.main()
