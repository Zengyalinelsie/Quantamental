"""In-memory canonical metric registry repository."""

from __future__ import annotations

from typing import TypeVar

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.metrics import (
    CanonicalMetric,
    FinancialQualityRule,
    MappingVersion,
    ProviderFieldMapping,
    StatementType,
    UnmappedProviderField,
)

_Value = TypeVar(
    "_Value",
    CanonicalMetric,
    MappingVersion,
    ProviderFieldMapping,
    FinancialQualityRule,
    UnmappedProviderField,
)


class InMemoryMetricRegistryRepository:
    def __init__(self) -> None:
        self._metrics: dict[str, CanonicalMetric] = {}
        self._versions: dict[str, MappingVersion] = {}
        self._mappings: dict[str, ProviderFieldMapping] = {}
        self._quality_rules: dict[str, FinancialQualityRule] = {}
        self._unmapped: dict[str, UnmappedProviderField] = {}

    @staticmethod
    def _register(values: dict[str, _Value], identifier: str, value: _Value) -> _Value:
        if existing := values.get(identifier):
            if existing != value:
                raise VersionConflictError(f"immutable identifier conflict: {identifier}")
            return existing
        values[identifier] = value
        return value

    def register_metric(self, value: CanonicalMetric) -> CanonicalMetric:
        return self._register(self._metrics, value.metric_code, value)

    def get_metric(self, metric_code: str) -> CanonicalMetric | None:
        return self._metrics.get(metric_code)

    def register_mapping_version(self, value: MappingVersion) -> MappingVersion:
        return self._register(self._versions, value.mapping_version_id, value)

    def get_mapping_version(self, mapping_version_id: str) -> MappingVersion | None:
        return self._versions.get(mapping_version_id)

    def register_mapping(self, value: ProviderFieldMapping) -> ProviderFieldMapping:
        return self._register(self._mappings, value.mapping_id, value)

    def find_mappings(
        self,
        *,
        provider_id: str,
        statement_type: StatementType,
        source_field: str,
        mapping_version_id: str,
    ) -> tuple[ProviderFieldMapping, ...]:
        statement_type = StatementType(statement_type)
        return tuple(
            value
            for value in self._mappings.values()
            if value.provider_id == provider_id
            and value.statement_type is statement_type
            and value.source_field == source_field
            and value.mapping_version_id == mapping_version_id
        )

    def register_quality_rule(self, value: FinancialQualityRule) -> FinancialQualityRule:
        return self._register(self._quality_rules, value.rule_id, value)

    def enqueue_unmapped_field(self, value: UnmappedProviderField) -> UnmappedProviderField:
        return self._register(self._unmapped, value.unmapped_field_id, value)

    def list_unmapped_fields(self) -> tuple[UnmappedProviderField, ...]:
        return tuple(self._unmapped.values())
