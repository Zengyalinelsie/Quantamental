"""Use cases for canonical metric registration and explicit provider resolution."""

from __future__ import annotations

from datetime import datetime

from a_share_platform.domain.metrics import (
    CanonicalMetric,
    FinancialQualityRule,
    MappingMethod,
    MappingUseScope,
    MappingVersion,
    ProviderFieldMapping,
    StatementType,
    UnmappedProviderField,
)
from a_share_platform.ports.metrics import MetricRegistryRepository


class MetricMappingConflictError(RuntimeError):
    """Raised when an input field maps to multiple canonical metrics."""


class MetricRegistryService:
    def __init__(self, repository: MetricRegistryRepository) -> None:
        self._repository = repository

    def register_metric(self, value: CanonicalMetric) -> CanonicalMetric:
        return self._repository.register_metric(value)

    def register_mapping_version(self, value: MappingVersion) -> MappingVersion:
        return self._repository.register_mapping_version(value)

    def register_mapping(self, value: ProviderFieldMapping) -> ProviderFieldMapping:
        metric = self._repository.get_metric(value.metric_code)
        if metric is None:
            raise ValueError(f"canonical metric does not exist: {value.metric_code}")
        if metric.statement_type is not value.statement_type:
            raise ValueError("mapping statement type does not match canonical metric")
        version = self._repository.get_mapping_version(value.mapping_version_id)
        if version is None:
            raise ValueError(f"mapping version does not exist: {value.mapping_version_id}")
        if version.provider_id != value.provider_id:
            raise ValueError("mapping provider does not match mapping version provider")
        existing = self._repository.find_mappings(
            provider_id=value.provider_id,
            statement_type=value.statement_type,
            source_field=value.source_field,
            mapping_version_id=value.mapping_version_id,
        )
        if existing and all(item.mapping_id != value.mapping_id for item in existing):
            raise MetricMappingConflictError(
                "provider field already has a mapping in this mapping version"
            )
        return self._repository.register_mapping(value)

    def register_quality_rule(self, value: FinancialQualityRule) -> FinancialQualityRule:
        for term in value.terms:
            if self._repository.get_metric(term.metric_code) is None:
                raise ValueError(f"canonical metric does not exist: {term.metric_code}")
        return self._repository.register_quality_rule(value)

    def resolve_or_queue(
        self,
        *,
        provider_id: str,
        statement_type: StatementType,
        source_field: str,
        mapping_version_id: str,
        use_scope: MappingUseScope,
        unmapped_field_id: str,
        discovered_at: datetime,
        raw_object_id: str,
    ) -> ProviderFieldMapping | None:
        use_scope = MappingUseScope(use_scope)
        version = self._repository.get_mapping_version(mapping_version_id)
        if version is None:
            raise ValueError(f"mapping version does not exist: {mapping_version_id}")
        if version.provider_id != provider_id:
            raise ValueError("provider does not match mapping version provider")
        mappings = self._repository.find_mappings(
            provider_id=provider_id,
            statement_type=statement_type,
            source_field=source_field,
            mapping_version_id=mapping_version_id,
        )
        if len(mappings) > 1:
            raise MetricMappingConflictError(
                "multiple mappings match one provider field; resolution fails closed"
            )
        if mappings:
            mapping = mappings[0]
            if not mapping.allows(use_scope) or (
                use_scope is MappingUseScope.PRODUCTION
                and mapping.method is MappingMethod.FUZZY
            ):
                raise PermissionError(
                    f"mapping is not allowed for {use_scope.value}"
                )
            return mapping
        self._repository.enqueue_unmapped_field(
            UnmappedProviderField(
                unmapped_field_id=unmapped_field_id,
                provider_id=provider_id,
                statement_type=statement_type,
                source_field=source_field,
                mapping_version_id=mapping_version_id,
                discovered_at=discovered_at,
                raw_object_id=raw_object_id,
            )
        )
        return None
