import unittest
from datetime import UTC, datetime

from a_share_platform.adapters.memory.metrics import InMemoryMetricRegistryRepository
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.metrics import (
    CanonicalMetric,
    CurrencyRequirement,
    MappingMethod,
    MappingUseScope,
    MappingVersion,
    MetricUnit,
    ProviderFieldMapping,
    SignConvention,
    StatementType,
)

NOW = datetime(2026, 8, 11, 3, tzinfo=UTC)


def _mapping(
    *,
    provider_id: str = "provider:qualified",
    allowed_use_scopes: frozenset[MappingUseScope],
    method: MappingMethod = MappingMethod.EXACT,
) -> ProviderFieldMapping:
    return ProviderFieldMapping(
        mapping_id=f"mapping:{provider_id}:total-assets:v1",
        mapping_version_id=f"mapping-version:{provider_id}:v1",
        provider_id=provider_id,
        statement_type=StatementType.BALANCE_SHEET,
        source_field="total_assets",
        metric_code="total_assets",
        method=method,
        formula=None,
        allowed_use_scopes=allowed_use_scopes,
    )


class MappingUseScopeTest(unittest.TestCase):
    def test_scope_is_explicit_and_production_does_not_imply_current_research(self) -> None:
        current = _mapping(
            allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH})
        )
        production = _mapping(
            allowed_use_scopes=frozenset({MappingUseScope.PRODUCTION})
        )

        self.assertTrue(current.allows(MappingUseScope.CURRENT_RESEARCH))
        self.assertFalse(current.allows(MappingUseScope.STRICT_HISTORICAL))
        self.assertFalse(current.allows(MappingUseScope.PRODUCTION))
        self.assertFalse(production.allows(MappingUseScope.CURRENT_RESEARCH))

    def test_empty_scope_and_fuzzy_production_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "allowed_use_scopes"):
            _mapping(allowed_use_scopes=frozenset())
        with self.assertRaisesRegex(ValueError, "fuzzy.*production"):
            _mapping(
                method=MappingMethod.FUZZY,
                allowed_use_scopes=frozenset({MappingUseScope.PRODUCTION}),
            )
        fuzzy_research = _mapping(
            method=MappingMethod.FUZZY,
            allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH}),
        )
        self.assertTrue(fuzzy_research.allows(MappingUseScope.CURRENT_RESEARCH))

    def test_akshare_mapping_can_only_be_current_research(self) -> None:
        current = _mapping(
            provider_id="akshare",
            allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH}),
        )
        self.assertTrue(current.allows(MappingUseScope.CURRENT_RESEARCH))
        for forbidden in (
            MappingUseScope.STRICT_HISTORICAL,
            MappingUseScope.PRODUCTION,
        ):
            with self.subTest(forbidden=forbidden), self.assertRaisesRegex(
                ValueError, "AkShare.*current_research"
            ):
                _mapping(
                    provider_id="akshare",
                    allowed_use_scopes=frozenset(
                        {MappingUseScope.CURRENT_RESEARCH, forbidden}
                    ),
                )


class MappingUseScopeResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryMetricRegistryRepository()
        self.service = MetricRegistryService(self.repository)
        self.service.register_metric(
            CanonicalMetric(
                metric_code="total_assets",
                canonical_name="Total Assets",
                statement_type=StatementType.BALANCE_SHEET,
                unit=MetricUnit.CURRENCY,
                currency_requirement=CurrencyRequirement.REQUIRED,
                sign_convention=SignConvention.NATURAL,
                description="Canonical total assets",
            )
        )
        self.service.register_mapping_version(
            MappingVersion(
                mapping_version_id="mapping-version:provider:qualified:v1",
                provider_id="provider:qualified",
                created_at=NOW,
                content_hash="sha256:" + "a" * 64,
                code_version="git:test",
            )
        )

    def test_resolution_requires_the_requested_scope(self) -> None:
        value = self.service.register_mapping(
            _mapping(
                allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH})
            )
        )
        common = {
            "provider_id": value.provider_id,
            "statement_type": value.statement_type,
            "source_field": value.source_field,
            "mapping_version_id": value.mapping_version_id,
            "unmapped_field_id": "unmapped:not-used",
            "discovered_at": NOW,
            "raw_object_id": "raw:not-used",
        }

        self.assertEqual(
            self.service.resolve_or_queue(
                **common,
                use_scope=MappingUseScope.CURRENT_RESEARCH,
            ),
            value,
        )
        for forbidden in (
            MappingUseScope.STRICT_HISTORICAL,
            MappingUseScope.PRODUCTION,
        ):
            with self.subTest(forbidden=forbidden), self.assertRaisesRegex(
                PermissionError, forbidden.value
            ):
                self.service.resolve_or_queue(**common, use_scope=forbidden)


if __name__ == "__main__":
    unittest.main()
