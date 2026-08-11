import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.industry_templates import (
    CompanyExceptionCategory,
    CompanyExceptionDecision,
    CompanyFeatureException,
    FeatureSourceLayer,
    GovernanceApprovalStatus,
    IndustryTemplateId,
    ThresholdBinding,
    ThresholdRequirement,
    industry_template_catalog_v0,
)

AS_OF = date(2026, 8, 11)
APPROVED_AT = datetime(2026, 8, 10, 8, tzinfo=UTC)


def approved_binding(requirement: ThresholdRequirement) -> ThresholdBinding:
    return ThresholdBinding(
        threshold_key=requirement.threshold_key,
        value=Decimal(1),
        unit=requirement.unit,
        source_kind=requirement.source_kind,
        source_id=f"source:{requirement.threshold_key}",
        source_version="threshold-source:v1",
        content_hash="sha256:" + "a" * 64,
        effective_from=date(2026, 1, 1),
        effective_to=None,
        approval_status=GovernanceApprovalStatus.APPROVED,
        approval_id="approval:threshold:v1",
        approved_by="reviewer:fundamental-methodology",
        approved_at=APPROVED_AT,
    )


class IndustryTemplateCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = industry_template_catalog_v0()

    def test_v0_contains_three_distinct_templates_with_complete_contracts(self) -> None:
        self.assertEqual(
            tuple(value.template_id for value in self.catalog.templates),
            (
                IndustryTemplateId.NON_FINANCIAL_GENERAL,
                IndustryTemplateId.BANK,
                IndustryTemplateId.MANUFACTURING_CONSUMER,
            ),
        )
        for template in self.catalog.templates:
            with self.subTest(template=template.template_id):
                self.assertTrue(template.version)
                self.assertTrue(template.key_metric_rules)
                self.assertTrue(template.incomparable_metric_codes)
                self.assertTrue(template.threshold_requirements)
                self.assertEqual(
                    {rule.source_layer for rule in template.key_metric_rules},
                    {FeatureSourceLayer.UNIVERSAL, FeatureSourceLayer.INDUSTRY},
                )
                self.assertEqual(
                    {rule.threshold_key for rule in template.key_metric_rules},
                    {
                        requirement.threshold_key
                        for requirement in template.threshold_requirements
                    },
                )
                self.assertEqual(
                    set(template.exception_policy.allowed_categories),
                    set(CompanyExceptionCategory),
                )

    def test_bank_and_manufacturing_do_not_share_industry_formula_or_inputs(self) -> None:
        bank = self.catalog.get(IndustryTemplateId.BANK)
        manufacturing = self.catalog.get(IndustryTemplateId.MANUFACTURING_CONSUMER)
        bank_rules = tuple(
            rule
            for rule in bank.key_metric_rules
            if rule.source_layer is FeatureSourceLayer.INDUSTRY
        )
        manufacturing_rules = tuple(
            rule
            for rule in manufacturing.key_metric_rules
            if rule.source_layer is FeatureSourceLayer.INDUSTRY
        )

        self.assertTrue(
            {rule.formula_id for rule in bank_rules}.isdisjoint(
                rule.formula_id for rule in manufacturing_rules
            )
        )
        self.assertNotEqual(
            {field for rule in bank_rules for field in rule.input_metric_codes},
            {
                field
                for rule in manufacturing_rules
                for field in rule.input_metric_codes
            },
        )
        self.assertIn("manufacturing.inventory_turnover", bank.incomparable_metric_codes)
        self.assertIn("bank.net_interest_margin", manufacturing.incomparable_metric_codes)

    def test_definition_hash_covers_the_human_readable_template_name(self) -> None:
        template = self.catalog.get(IndustryTemplateId.BANK)

        renamed = replace(template, name="Renamed bank quality template")

        self.assertNotEqual(renamed.definition_hash, template.definition_hash)

    def test_feature_resolution_marks_universal_and_industry_sources(self) -> None:
        bank = self.catalog.get(IndustryTemplateId.BANK)
        universal = next(
            rule
            for rule in bank.key_metric_rules
            if rule.source_layer is FeatureSourceLayer.UNIVERSAL
        )
        industry = next(
            rule
            for rule in bank.key_metric_rules
            if rule.source_layer is FeatureSourceLayer.INDUSTRY
        )
        bindings = tuple(approved_binding(value) for value in bank.threshold_requirements)

        universal_result = self.catalog.resolve_feature(
            template_id=bank.template_id,
            feature_id=universal.feature_id,
            company_id="company:bank-a",
            as_of=AS_OF,
            threshold_bindings=bindings,
        )
        industry_result = self.catalog.resolve_feature(
            template_id=bank.template_id,
            feature_id=industry.feature_id,
            company_id="company:bank-a",
            as_of=AS_OF,
            threshold_bindings=bindings,
        )

        self.assertTrue(universal_result.applicable)
        self.assertEqual(
            universal_result.provenance.source_layer,
            FeatureSourceLayer.UNIVERSAL,
        )
        self.assertEqual(
            industry_result.provenance.source_layer,
            FeatureSourceLayer.INDUSTRY,
        )
        self.assertEqual(
            industry_result.threshold_binding.threshold_key,  # type: ignore[union-attr]
            industry.threshold_key,
        )

    def test_missing_or_unapproved_threshold_fails_closed(self) -> None:
        template = self.catalog.get(IndustryTemplateId.NON_FINANCIAL_GENERAL)
        rule = template.key_metric_rules[0]
        requirement = template.threshold_requirement(rule.threshold_key)

        with self.assertRaisesRegex(LookupError, "threshold binding is missing"):
            self.catalog.resolve_feature(
                template_id=template.template_id,
                feature_id=rule.feature_id,
                company_id="company:industrial-a",
                as_of=AS_OF,
                threshold_bindings=(),
            )

        pending = replace(
            approved_binding(requirement),
            approval_status=GovernanceApprovalStatus.PENDING,
            approval_id=None,
            approved_by=None,
            approved_at=None,
        )
        with self.assertRaisesRegex(PermissionError, "threshold.*not approved"):
            self.catalog.resolve_feature(
                template_id=template.template_id,
                feature_id=rule.feature_id,
                company_id="company:industrial-a",
                as_of=AS_OF,
                threshold_bindings=(pending,),
            )

    def test_threshold_source_kind_version_and_effective_date_are_enforced(self) -> None:
        template = self.catalog.get(IndustryTemplateId.BANK)
        rule = next(
            item
            for item in template.key_metric_rules
            if item.source_layer is FeatureSourceLayer.INDUSTRY
        )
        requirement = template.threshold_requirement(rule.threshold_key)
        valid = approved_binding(requirement)

        for invalid, message in (
            (
                replace(valid, source_kind="peer_distribution"),
                "source kind",
            ),
            (
                replace(valid, effective_from=date(2027, 1, 1)),
                "not effective",
            ),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                (ValueError, PermissionError), message
            ):
                self.catalog.resolve_feature(
                    template_id=template.template_id,
                    feature_id=rule.feature_id,
                    company_id="company:bank-a",
                    as_of=AS_OF,
                    threshold_bindings=(invalid,),
                )

    def test_pending_company_exception_cannot_change_feature_provenance(self) -> None:
        template = self.catalog.get(IndustryTemplateId.MANUFACTURING_CONSUMER)
        rule = next(
            item
            for item in template.key_metric_rules
            if item.source_layer is FeatureSourceLayer.INDUSTRY
        )
        pending = CompanyFeatureException(
            exception_id="company-exception:factory-a:inventory:v1",
            company_id="company:factory-a",
            template_id=template.template_id,
            feature_id=rule.feature_id,
            category=CompanyExceptionCategory.MATERIAL_EVENT,
            decision=CompanyExceptionDecision.NOT_APPLICABLE,
            rationale="Factory relocation makes this period structurally incomparable.",
            evidence_ids=("disclosure:factory-relocation:v1",),
            status=GovernanceApprovalStatus.PENDING,
            approval_id=None,
            approved_by=None,
            approved_at=None,
        )

        with self.assertRaisesRegex(PermissionError, "company exception is not approved"):
            self.catalog.resolve_feature(
                template_id=template.template_id,
                feature_id=rule.feature_id,
                company_id=pending.company_id,
                as_of=AS_OF,
                threshold_bindings=(),
                company_exception=pending,
            )

    def test_approved_company_exception_is_explicit_and_never_invents_a_threshold(
        self,
    ) -> None:
        template = self.catalog.get(IndustryTemplateId.MANUFACTURING_CONSUMER)
        rule = next(
            item
            for item in template.key_metric_rules
            if item.source_layer is FeatureSourceLayer.INDUSTRY
        )
        approved = CompanyFeatureException(
            exception_id="company-exception:factory-a:inventory:v1",
            company_id="company:factory-a",
            template_id=template.template_id,
            feature_id=rule.feature_id,
            category=CompanyExceptionCategory.MATERIAL_EVENT,
            decision=CompanyExceptionDecision.NOT_APPLICABLE,
            rationale="Factory relocation makes this period structurally incomparable.",
            evidence_ids=("disclosure:factory-relocation:v1",),
            status=GovernanceApprovalStatus.APPROVED,
            approval_id="approval:company-exception:v1",
            approved_by="reviewer:fundamental-methodology",
            approved_at=APPROVED_AT,
        )

        result = self.catalog.resolve_feature(
            template_id=template.template_id,
            feature_id=rule.feature_id,
            company_id=approved.company_id,
            as_of=AS_OF,
            threshold_bindings=(),
            company_exception=approved,
        )

        self.assertFalse(result.applicable)
        self.assertIsNone(result.rule)
        self.assertIsNone(result.threshold_binding)
        self.assertEqual(
            result.provenance.source_layer,
            FeatureSourceLayer.COMPANY_EXCEPTION,
        )
        self.assertEqual(result.provenance.exception_id, approved.exception_id)

    def test_exception_scope_cannot_leak_to_another_company_or_feature(self) -> None:
        template = self.catalog.get(IndustryTemplateId.BANK)
        rule = template.key_metric_rules[0]
        approved = CompanyFeatureException(
            exception_id="company-exception:bank-a:cash:v1",
            company_id="company:bank-a",
            template_id=template.template_id,
            feature_id=rule.feature_id,
            category=CompanyExceptionCategory.ACCOUNTING_POLICY,
            decision=CompanyExceptionDecision.USE_TEMPLATE_RULE_WITH_DISCLOSURE,
            rationale="Presentation changed but the governed template remains applicable.",
            evidence_ids=("disclosure:accounting-policy:v1",),
            status=GovernanceApprovalStatus.APPROVED,
            approval_id="approval:company-exception:v2",
            approved_by="reviewer:fundamental-methodology",
            approved_at=APPROVED_AT,
        )
        requirement = template.threshold_requirement(rule.threshold_key)

        with self.assertRaisesRegex(ValueError, "company exception scope"):
            self.catalog.resolve_feature(
                template_id=template.template_id,
                feature_id=rule.feature_id,
                company_id="company:bank-b",
                as_of=AS_OF,
                threshold_bindings=(approved_binding(requirement),),
                company_exception=approved,
            )


if __name__ == "__main__":
    unittest.main()
