import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.features import FeatureCalculationStatus, FeaturePeriod
from a_share_platform.domain.industry_templates import (
    GovernanceApprovalStatus,
    IndustryTemplateId,
    ThresholdBinding,
    ThresholdRequirement,
    industry_template_catalog_v0,
)
from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.quality_factor import (
    FactorScientificStatus,
    QualityComponentInput,
    QualityCoverageStatus,
    QualityFactorDefinition,
    QualityFactorExposures,
    quality_factor_definition_v0,
)

AS_OF = date(2026, 8, 11)
APPROVED_AT = datetime(2026, 8, 10, 8, tzinfo=UTC)
THRESHOLDS = {
    "universal.cash_flow_to_profit.minimum": Decimal("1.0"),
    "universal.balance_sheet_leverage.maximum": Decimal("0.7"),
    "non_financial.roic.minimum": Decimal("0.10"),
    "non_financial.interest_coverage.minimum": Decimal("3.0"),
    "bank.core_tier1_capital_adequacy.minimum": Decimal("0.08"),
    "bank.nonperforming_loan_ratio.maximum": Decimal("0.02"),
    "bank.net_interest_margin.minimum": Decimal("0.02"),
    "bank.accruals.maximum": Decimal("0.02"),
    "bank.roe.minimum": Decimal("0.12"),
    "bank.net_interest_margin_stability.minimum": Decimal("0.80"),
    "non_financial.accruals.maximum": Decimal("0.05"),
    "non_financial.roe.minimum": Decimal("0.12"),
    "non_financial.net_margin_stability.minimum": Decimal("0.80"),
    "manufacturing.gross_margin_stability.minimum": Decimal("0.30"),
    "manufacturing.inventory_turnover.minimum": Decimal("4.0"),
    "manufacturing.cash_conversion_cycle.maximum": Decimal(60),
}


def binding(requirement: ThresholdRequirement) -> ThresholdBinding:
    return ThresholdBinding(
        threshold_key=requirement.threshold_key,
        value=THRESHOLDS[requirement.threshold_key],
        unit=requirement.unit,
        source_kind=requirement.source_kind,
        source_id=f"threshold-source:{requirement.threshold_key}",
        source_version="threshold-source:v1",
        content_hash="sha256:" + "a" * 64,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        approval_status=GovernanceApprovalStatus.APPROVED,
        approval_id="approval:quality-thresholds:v1",
        approved_by="reviewer:fundamental-methodology",
        approved_at=APPROVED_AT,
    )


def inputs_for(
    template_id: IndustryTemplateId,
    values: dict[str, Decimal | None],
) -> tuple[QualityFactorDefinition, dict[str, QualityComponentInput]]:
    catalog = industry_template_catalog_v0()
    definition = quality_factor_definition_v0(template_id, catalog=catalog)
    template = catalog.get(template_id)
    bindings = tuple(binding(value) for value in template.threshold_requirements)
    inputs = {
        component.feature_id: QualityComponentInput(
            feature_id=component.feature_id,
            value=values.get(component.feature_id),
            unit=component.unit,
            period=component.period,
            resolved_feature=catalog.resolve_feature(
                template_id=template_id,
                feature_id=component.feature_id,
                company_id=f"company:{template_id.value}:fixture",
                as_of=AS_OF,
                threshold_bindings=bindings,
            ),
        )
        for component in definition.components
    }
    return definition, inputs


def exposures(
    *,
    industry_code: str | None = "industry:fixture",
    log_market_cap: Decimal | None = Decimal("23.5"),
    beta: Decimal | None = Decimal("1.1"),
) -> QualityFactorExposures:
    return QualityFactorExposures(
        industry_code=industry_code,
        log_market_cap=log_market_cap,
        beta=beta,
    )


class QualityFactorV0Test(unittest.TestCase):
    def test_four_company_hand_calculations_use_template_specific_pass_rates(
        self,
    ) -> None:
        cases = (
            (
                "bank-a",
                IndustryTemplateId.BANK,
                {
                    "quality.universal.cash_flow_to_profit": Decimal("1.2"),
                    "quality.universal.balance_sheet_leverage": Decimal("0.6"),
                    "quality.bank.core_tier1_capital_adequacy": Decimal("0.10"),
                    "quality.bank.nonperforming_loan_ratio": Decimal("0.03"),
                    "quality.bank.net_interest_margin": Decimal("0.025"),
                    "quality.bank.accruals": Decimal("0.01"),
                    "quality.bank.roe": Decimal("0.15"),
                    "quality.bank.net_interest_margin_stability": Decimal("0.90"),
                },
                Decimal("0.875"),
            ),
            (
                "bank-b",
                IndustryTemplateId.BANK,
                {
                    "quality.universal.cash_flow_to_profit": Decimal("0.8"),
                    "quality.universal.balance_sheet_leverage": Decimal("0.8"),
                    "quality.bank.core_tier1_capital_adequacy": Decimal("0.07"),
                    "quality.bank.nonperforming_loan_ratio": Decimal("0.01"),
                    "quality.bank.net_interest_margin": Decimal("0.03"),
                    "quality.bank.accruals": Decimal("0.03"),
                    "quality.bank.roe": Decimal("0.10"),
                    "quality.bank.net_interest_margin_stability": Decimal("0.70"),
                },
                Decimal("0.25"),
            ),
            (
                "manufacturer-a",
                IndustryTemplateId.MANUFACTURING_CONSUMER,
                {
                    "quality.universal.cash_flow_to_profit": Decimal("1.1"),
                    "quality.universal.balance_sheet_leverage": Decimal("0.65"),
                    "quality.manufacturing.gross_margin_stability": Decimal("0.35"),
                    "quality.manufacturing.inventory_turnover": Decimal("3.0"),
                    "quality.manufacturing.cash_conversion_cycle": Decimal(50),
                    "quality.non_financial.accruals": Decimal("0.04"),
                    "quality.non_financial.roe": Decimal("0.15"),
                    "quality.non_financial.net_margin_stability": Decimal("0.75"),
                },
                Decimal("0.75"),
            ),
            (
                "manufacturer-b-boundaries",
                IndustryTemplateId.MANUFACTURING_CONSUMER,
                {
                    "quality.universal.cash_flow_to_profit": Decimal("1.0"),
                    "quality.universal.balance_sheet_leverage": Decimal("0.7"),
                    "quality.manufacturing.gross_margin_stability": Decimal("0.30"),
                    "quality.manufacturing.inventory_turnover": Decimal("4.0"),
                    "quality.manufacturing.cash_conversion_cycle": Decimal(60),
                    "quality.non_financial.accruals": Decimal("0.05"),
                    "quality.non_financial.roe": Decimal("0.12"),
                    "quality.non_financial.net_margin_stability": Decimal("0.80"),
                },
                Decimal(1),
            ),
        )

        for name, template_id, values, expected in cases:
            with self.subTest(company=name):
                definition, inputs = inputs_for(template_id, values)
                result = definition.calculate(inputs, exposures=exposures())

                self.assertEqual(result.status, FeatureCalculationStatus.QUANTIFIED)
                self.assertEqual(result.value, expected)
                self.assertEqual(result.formula_version, "v0")
                self.assertEqual(
                    result.scientific_status,
                    FactorScientificStatus.NOT_EVALUATED,
                )

    def test_bank_and_manufacturing_use_distinct_industry_components_and_provenance(
        self,
    ) -> None:
        catalog = industry_template_catalog_v0()
        bank = quality_factor_definition_v0(IndustryTemplateId.BANK, catalog=catalog)
        manufacturing = quality_factor_definition_v0(
            IndustryTemplateId.MANUFACTURING_CONSUMER,
            catalog=catalog,
        )
        bank_industry = {
            value.feature_id for value in bank.components if value.is_industry_specific
        }
        manufacturing_industry = {
            value.feature_id for value in manufacturing.components if value.is_industry_specific
        }

        self.assertTrue(bank_industry)
        self.assertTrue(manufacturing_industry)
        self.assertTrue(bank_industry.isdisjoint(manufacturing_industry))
        self.assertEqual(
            bank.template_definition_hash, catalog.get(bank.template_id).definition_hash
        )
        self.assertEqual(
            manufacturing.template_definition_hash,
            catalog.get(manufacturing.template_id).definition_hash,
        )
        self.assertEqual(bank.coverage_status, QualityCoverageStatus.PARTIAL)
        non_financial = quality_factor_definition_v0(
            IndustryTemplateId.NON_FINANCIAL_GENERAL,
            catalog=catalog,
        )
        for definition in (non_financial, bank, manufacturing):
            with self.subTest(coverage=definition.template_id):
                self.assertNotIn("spec017.accruals", definition.coverage_gaps)
                self.assertNotIn("spec017.roe", definition.coverage_gaps)
                self.assertNotIn(
                    "spec017.net_margin_stability",
                    definition.coverage_gaps,
                )
                self.assertIn("spec017.dilution", definition.coverage_gaps)
                self.assertIn(
                    "spec017.audit_and_regulatory",
                    definition.coverage_gaps,
                )
        self.assertNotEqual(bank.coverage_gaps, ())
        for definition, expected_ids in (
            (
                bank,
                {
                    "quality.bank.accruals",
                    "quality.bank.roe",
                    "quality.bank.net_interest_margin_stability",
                },
            ),
            (
                manufacturing,
                {
                    "quality.non_financial.accruals",
                    "quality.non_financial.roe",
                    "quality.non_financial.net_margin_stability",
                },
            ),
        ):
            periods = {
                component.feature_id: component.period
                for component in definition.components
                if component.feature_id in expected_ids
            }
            self.assertEqual(set(periods), expected_ids)
            self.assertEqual(set(periods.values()), {FeaturePeriod.TTM})

    def test_missing_component_is_unavailable_and_never_zero_filled(self) -> None:
        definition, inputs = inputs_for(
            IndustryTemplateId.BANK,
            {
                "quality.universal.cash_flow_to_profit": Decimal("1.2"),
                "quality.universal.balance_sheet_leverage": Decimal("0.6"),
                "quality.bank.core_tier1_capital_adequacy": Decimal("0.10"),
                "quality.bank.nonperforming_loan_ratio": Decimal("0.01"),
                "quality.bank.net_interest_margin": Decimal("0.025"),
                "quality.bank.accruals": None,
                "quality.bank.roe": Decimal("0.15"),
                "quality.bank.net_interest_margin_stability": Decimal("0.90"),
            },
        )

        result = definition.calculate(inputs, exposures=exposures())

        self.assertEqual(result.status, FeatureCalculationStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertEqual(
            result.missing_component_ids,
            ("quality.bank.accruals",),
        )
        missing = next(
            value
            for value in result.component_results
            if value.feature_id == "quality.bank.accruals"
        )
        self.assertIsNone(missing.value)
        self.assertIsNone(missing.passed)

    def test_component_unit_period_and_template_provenance_fail_closed(self) -> None:
        definition, inputs = inputs_for(
            IndustryTemplateId.MANUFACTURING_CONSUMER,
            {
                component.feature_id: Decimal(1)
                for component in quality_factor_definition_v0(
                    IndustryTemplateId.MANUFACTURING_CONSUMER
                ).components
            },
        )
        target = "quality.manufacturing.inventory_turnover"

        for label, invalid in (
            ("unit", replace(inputs[target], unit=MetricUnit.DAYS)),
            ("period", replace(inputs[target], period=FeaturePeriod.ANNUAL)),
        ):
            with self.subTest(label=label):
                altered = dict(inputs)
                altered[target] = invalid
                with self.assertRaisesRegex(ValueError, label):
                    definition.calculate(altered, exposures=exposures())

        bank_definition, bank_inputs = inputs_for(
            IndustryTemplateId.BANK,
            {
                component.feature_id: Decimal(1)
                for component in quality_factor_definition_v0(IndustryTemplateId.BANK).components
            },
        )
        altered = dict(inputs)
        altered[target] = replace(
            altered[target],
            resolved_feature=next(iter(bank_inputs.values())).resolved_feature,
        )
        with self.assertRaisesRegex(ValueError, "provenance|template|feature"):
            definition.calculate(altered, exposures=exposures())
        self.assertNotEqual(definition.template_id, bank_definition.template_id)

    def test_size_industry_and_beta_are_exposures_not_quality_inputs(self) -> None:
        definition, inputs = inputs_for(
            IndustryTemplateId.BANK,
            {
                component.feature_id: Decimal(1)
                for component in quality_factor_definition_v0(IndustryTemplateId.BANK).components
            },
        )
        first = definition.calculate(
            inputs,
            exposures=exposures(
                industry_code="bank",
                log_market_cap=Decimal(20),
                beta=Decimal("0.7"),
            ),
        )
        second = definition.calculate(
            inputs,
            exposures=exposures(
                industry_code=None,
                log_market_cap=None,
                beta=None,
            ),
        )

        self.assertEqual(first.value, second.value)
        self.assertEqual(
            second.exposures.missing_exposure_names,
            ("industry", "size", "beta"),
        )
        self.assertTrue(
            {"industry", "size", "beta"}.isdisjoint(
                component.feature_id for component in definition.components
            )
        )


if __name__ == "__main__":
    unittest.main()
