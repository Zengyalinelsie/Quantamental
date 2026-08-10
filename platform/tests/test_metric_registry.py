import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.adapters.memory.metrics import InMemoryMetricRegistryRepository
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.metrics import (
    CanonicalMetric,
    CurrencyRequirement,
    FinancialQualityRule,
    MappingMethod,
    MappingVersion,
    MetricUnit,
    ProviderFieldMapping,
    QualityRuleKind,
    QualitySeverity,
    QualityStatus,
    QualityTerm,
    SignConvention,
    StatementType,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def metric(
    metric_code: str,
    *,
    statement_type: StatementType = StatementType.BALANCE_SHEET,
    unit: MetricUnit = MetricUnit.CURRENCY,
    currency_requirement: CurrencyRequirement = CurrencyRequirement.REQUIRED,
) -> CanonicalMetric:
    return CanonicalMetric(
        metric_code=metric_code,
        canonical_name=metric_code.replace("_", " ").title(),
        statement_type=statement_type,
        unit=unit,
        currency_requirement=currency_requirement,
        sign_convention=SignConvention.NATURAL,
        description=f"Canonical {metric_code}",
    )


def mapping_version(*, content_hash: str = HASH_A) -> MappingVersion:
    return MappingVersion(
        mapping_version_id="metric-mapping:tushare:v1",
        provider_id="provider:tushare",
        created_at=NOW,
        content_hash=content_hash,
        code_version="git:abc123",
    )


def mapping(
    *,
    mapping_id: str = "mapping:tushare:balancesheet:total_assets:v1",
    metric_code: str = "total_assets",
    method: MappingMethod = MappingMethod.EXACT,
    production_allowed: bool = True,
) -> ProviderFieldMapping:
    return ProviderFieldMapping(
        mapping_id=mapping_id,
        mapping_version_id="metric-mapping:tushare:v1",
        provider_id="provider:tushare",
        statement_type=StatementType.BALANCE_SHEET,
        source_field="total_assets",
        metric_code=metric_code,
        method=method,
        formula=None,
        production_allowed=production_allowed,
    )


class CanonicalMetricTest(unittest.TestCase):
    def test_metric_has_statement_unit_currency_and_sign_contracts(self) -> None:
        value = metric("total_assets")
        self.assertEqual(value.statement_type, StatementType.BALANCE_SHEET)
        self.assertEqual(value.unit, MetricUnit.CURRENCY)
        self.assertEqual(value.currency_requirement, CurrencyRequirement.REQUIRED)
        self.assertEqual(value.sign_convention, SignConvention.NATURAL)

    def test_currency_unit_requires_currency_and_ratio_forbids_it(self) -> None:
        with self.assertRaisesRegex(ValueError, "currency unit"):
            metric(
                "total_assets",
                currency_requirement=CurrencyRequirement.FORBIDDEN,
            )
        with self.assertRaisesRegex(ValueError, "non-currency unit"):
            metric(
                "return_on_equity",
                unit=MetricUnit.RATIO,
                currency_requirement=CurrencyRequirement.REQUIRED,
            )


class ProviderFieldMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMetricRegistryRepository()
        self.service = MetricRegistryService(self.repository)
        self.service.register_metric(metric("total_assets"))
        self.service.register_mapping_version(mapping_version())

    def test_explicit_mapping_resolves_by_provider_statement_field_and_version(self) -> None:
        expected = self.service.register_mapping(mapping())
        actual = self.service.resolve_or_queue(
            provider_id="provider:tushare",
            statement_type=StatementType.BALANCE_SHEET,
            source_field="total_assets",
            mapping_version_id="metric-mapping:tushare:v1",
            for_production=True,
            unmapped_field_id="unmapped:not-used",
            discovered_at=NOW,
            raw_object_id="raw:tushare:balancesheet:1",
        )
        self.assertIs(actual, expected)
        self.assertEqual(self.repository.list_unmapped_fields(), ())

    def test_fuzzy_mapping_can_never_enter_production(self) -> None:
        with self.assertRaisesRegex(ValueError, "fuzzy"):
            mapping(method=MappingMethod.FUZZY, production_allowed=True)
        fuzzy = self.service.register_mapping(
            mapping(method=MappingMethod.FUZZY, production_allowed=False)
        )
        with self.assertRaisesRegex(PermissionError, "production"):
            self.service.resolve_or_queue(
                provider_id=fuzzy.provider_id,
                statement_type=fuzzy.statement_type,
                source_field=fuzzy.source_field,
                mapping_version_id=fuzzy.mapping_version_id,
                for_production=True,
                unmapped_field_id="unmapped:not-used",
                discovered_at=NOW,
                raw_object_id="raw:tushare:balancesheet:1",
            )

    def test_unknown_field_is_queued_and_never_returned_as_zero(self) -> None:
        actual = self.service.resolve_or_queue(
            provider_id="provider:tushare",
            statement_type=StatementType.BALANCE_SHEET,
            source_field="mystery_asset",
            mapping_version_id="metric-mapping:tushare:v1",
            for_production=False,
            unmapped_field_id="unmapped:tushare:mystery_asset:1",
            discovered_at=NOW,
            raw_object_id="raw:tushare:balancesheet:1",
        )
        self.assertIsNone(actual)
        queued = self.repository.list_unmapped_fields()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0].source_field, "mystery_asset")
        self.assertIsNone(queued[0].resolved_mapping_id)

    def test_mapping_versions_and_mapping_ids_are_immutable(self) -> None:
        version = mapping_version()
        self.assertEqual(self.service.register_mapping_version(version), version)
        with self.assertRaisesRegex(VersionConflictError, "metric-mapping:tushare:v1"):
            self.service.register_mapping_version(mapping_version(content_hash=HASH_B))

        registered = self.service.register_mapping(mapping())
        self.assertIs(self.service.register_mapping(registered), registered)
        self.service.register_metric(metric("other_assets"))
        with self.assertRaisesRegex(VersionConflictError, registered.mapping_id):
            self.service.register_mapping(replace(registered, metric_code="other_assets"))

    def test_mapping_rejects_unknown_metric_or_wrong_provider_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical metric does not exist"):
            self.service.register_mapping(mapping(metric_code="missing_metric"))
        with self.assertRaisesRegex(ValueError, "provider does not match"):
            self.service.register_mapping(replace(mapping(), provider_id="provider:other"))
        with self.assertRaisesRegex(ValueError, "statement type"):
            self.service.register_mapping(
                replace(mapping(), statement_type=StatementType.INCOME_STATEMENT)
            )


class FinancialQualityRuleTest(unittest.TestCase):
    def test_balance_equation_passes_and_blocks_material_mismatch(self) -> None:
        rule = FinancialQualityRule(
            rule_id="quality:balance-sheet-equation:v1",
            name="assets equal liabilities plus equity",
            rule_kind=QualityRuleKind.ACCOUNTING_IDENTITY,
            terms=(
                QualityTerm("total_assets", Decimal(1)),
                QualityTerm("total_liabilities", Decimal(-1)),
                QualityTerm("total_equity", Decimal(-1)),
            ),
            tolerance=Decimal("0.01"),
            severity=QualitySeverity.BLOCK,
        )
        passed = rule.evaluate(
            {
                "total_assets": Decimal(100),
                "total_liabilities": Decimal(60),
                "total_equity": Decimal(40),
            }
        )
        failed = rule.evaluate(
            {
                "total_assets": Decimal(100),
                "total_liabilities": Decimal(60),
                "total_equity": Decimal(30),
            }
        )
        self.assertEqual(passed.status, QualityStatus.PASSED)
        self.assertFalse(passed.blocks_downstream)
        self.assertEqual(failed.status, QualityStatus.FAILED)
        self.assertTrue(failed.blocks_downstream)
        self.assertEqual(failed.residual, Decimal(10))

    def test_missing_rule_input_is_unavailable_not_zero(self) -> None:
        rule = FinancialQualityRule(
            rule_id="quality:cash-reconciliation:v1",
            name="ending cash reconciliation",
            rule_kind=QualityRuleKind.CROSS_STATEMENT,
            terms=(
                QualityTerm("cash_end", Decimal(1)),
                QualityTerm("cash_begin", Decimal(-1)),
                QualityTerm("net_cash_increase", Decimal(-1)),
            ),
            tolerance=Decimal("0.01"),
            severity=QualitySeverity.BLOCK,
        )
        result = rule.evaluate(
            {
                "cash_end": Decimal(15),
                "cash_begin": Decimal(10),
                "net_cash_increase": None,
            }
        )
        self.assertEqual(result.status, QualityStatus.UNAVAILABLE)
        self.assertEqual(result.missing_metric_codes, ("net_cash_increase",))
        self.assertIsNone(result.residual)
        self.assertTrue(result.blocks_downstream)


if __name__ == "__main__":
    unittest.main()
