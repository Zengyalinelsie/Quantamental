"""Repository port for canonical financial metrics and mappings."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.metrics import (
    CanonicalMetric,
    FinancialQualityRule,
    MappingVersion,
    ProviderFieldMapping,
    StatementType,
    UnmappedProviderField,
)


class MetricRegistryRepository(Protocol):
    def register_metric(self, value: CanonicalMetric) -> CanonicalMetric: ...

    def get_metric(self, metric_code: str) -> CanonicalMetric | None: ...

    def register_mapping_version(self, value: MappingVersion) -> MappingVersion: ...

    def get_mapping_version(self, mapping_version_id: str) -> MappingVersion | None: ...

    def register_mapping(self, value: ProviderFieldMapping) -> ProviderFieldMapping: ...

    def find_mappings(
        self,
        *,
        provider_id: str,
        statement_type: StatementType,
        source_field: str,
        mapping_version_id: str,
    ) -> tuple[ProviderFieldMapping, ...]: ...

    def register_quality_rule(self, value: FinancialQualityRule) -> FinancialQualityRule: ...

    def enqueue_unmapped_field(self, value: UnmappedProviderField) -> UnmappedProviderField: ...

    def list_unmapped_fields(self) -> tuple[UnmappedProviderField, ...]: ...
