"""PostgreSQL repository for canonical metrics, mappings, and quality rules."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.metrics import (
    CanonicalMetric,
    CurrencyRequirement,
    FinancialQualityRule,
    MappingMethod,
    MappingUseScope,
    MappingVersion,
    MetricUnit,
    ProviderFieldMapping,
    QualityRuleKind,
    QualitySeverity,
    QualityTerm,
    SignConvention,
    StatementType,
    UnmappedFieldStatus,
    UnmappedProviderField,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, (dict, list)):
        return value
    obj = getattr(value, "obj", None)
    return value if obj is None else obj


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class PostgresMetricRegistryRepository:
    """Append-only registry; commit and rollback belong to the calling unit of work."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def register_metric(self, value: CanonicalMetric) -> CanonicalMetric:
        if not isinstance(value, CanonicalMetric):
            raise TypeError("value must be a CanonicalMetric")
        self._connection.execute(
            """
            INSERT INTO canonical_metrics (
                metric_code, canonical_name, statement_type, unit,
                currency_requirement, sign_convention, description
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            self._metric_row(value),
        )
        stored = self.get_metric(value.metric_code)
        if stored != value:
            raise VersionConflictError(
                f"immutable canonical metric conflict: {value.metric_code}"
            )
        return stored

    def get_metric(self, metric_code: str) -> CanonicalMetric | None:
        row = self._connection.execute(
            """
            SELECT metric_code, canonical_name, statement_type, unit,
                   currency_requirement, sign_convention, description
            FROM canonical_metrics WHERE metric_code = %s
            """,
            (metric_code,),
        ).fetchone()
        return None if row is None else self._metric_from_row(row)

    def register_mapping_version(self, value: MappingVersion) -> MappingVersion:
        if not isinstance(value, MappingVersion):
            raise TypeError("value must be a MappingVersion")
        self._connection.execute(
            """
            INSERT INTO metric_mapping_versions (
                mapping_version_id, provider_id, created_at, content_hash, code_version
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            self._mapping_version_row(value),
        )
        stored = self.get_mapping_version(value.mapping_version_id)
        if stored != value:
            raise VersionConflictError(
                f"immutable mapping version conflict: {value.mapping_version_id}"
            )
        return stored

    def get_mapping_version(self, mapping_version_id: str) -> MappingVersion | None:
        row = self._connection.execute(
            """
            SELECT mapping_version_id, provider_id, created_at, content_hash, code_version
            FROM metric_mapping_versions WHERE mapping_version_id = %s
            """,
            (mapping_version_id,),
        ).fetchone()
        return None if row is None else self._mapping_version_from_row(row)

    def register_mapping(self, value: ProviderFieldMapping) -> ProviderFieldMapping:
        if not isinstance(value, ProviderFieldMapping):
            raise TypeError("value must be a ProviderFieldMapping")
        self._connection.execute(
            """
            INSERT INTO provider_field_mappings (
                mapping_id, mapping_version_id, provider_id, statement_type,
                source_field, metric_code, method, formula, allowed_use_scopes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            self._mapping_row(value),
        )
        stored = self._get_mapping(value.mapping_id)
        if stored != value:
            raise VersionConflictError(
                f"immutable provider mapping conflict: {value.mapping_id}"
            )
        return stored

    def find_mappings(
        self,
        *,
        provider_id: str,
        statement_type: StatementType,
        source_field: str,
        mapping_version_id: str,
    ) -> tuple[ProviderFieldMapping, ...]:
        rows = self._connection.execute(
            """
            SELECT mapping_id, mapping_version_id, provider_id, statement_type,
                   source_field, metric_code, method, formula, allowed_use_scopes
            FROM provider_field_mappings
            WHERE provider_id = %s
              AND statement_type = %s
              AND source_field = %s
              AND mapping_version_id = %s
            ORDER BY mapping_id
            """,
            (
                provider_id,
                StatementType(statement_type).value,
                source_field,
                mapping_version_id,
            ),
        ).fetchall()
        return tuple(self._mapping_from_row(row) for row in rows)

    def register_quality_rule(self, value: FinancialQualityRule) -> FinancialQualityRule:
        if not isinstance(value, FinancialQualityRule):
            raise TypeError("value must be a FinancialQualityRule")
        terms = [
            {
                "metric_code": term.metric_code,
                "coefficient": str(term.coefficient),
            }
            for term in value.terms
        ]
        self._connection.execute(
            """
            INSERT INTO financial_quality_rules (
                rule_id, name, rule_kind, terms, tolerance, severity
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                value.rule_id,
                value.name,
                value.rule_kind.value,
                _json_parameter(terms),
                value.tolerance,
                value.severity.value,
            ),
        )
        stored = self._get_quality_rule(value.rule_id)
        if stored != value:
            raise VersionConflictError(f"immutable quality rule conflict: {value.rule_id}")
        return stored

    def enqueue_unmapped_field(self, value: UnmappedProviderField) -> UnmappedProviderField:
        if not isinstance(value, UnmappedProviderField):
            raise TypeError("value must be an UnmappedProviderField")
        self._connection.execute(
            """
            INSERT INTO unmapped_metric_fields (
                unmapped_field_id, provider_id, statement_type, source_field,
                mapping_version_id, discovered_at, raw_object_id, status,
                resolved_mapping_id, resolution_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            self._unmapped_row(value),
        )
        stored = self._get_unmapped_field(value.unmapped_field_id)
        if stored != value:
            raise VersionConflictError(
                f"immutable unmapped field conflict: {value.unmapped_field_id}"
            )
        return stored

    def list_unmapped_fields(self) -> tuple[UnmappedProviderField, ...]:
        rows = self._connection.execute(
            """
            SELECT unmapped_field_id, provider_id, statement_type, source_field,
                   mapping_version_id, discovered_at, raw_object_id, status,
                   resolved_mapping_id, resolution_reason
            FROM unmapped_metric_fields
            ORDER BY status, discovered_at, unmapped_field_id
            """
        ).fetchall()
        return tuple(self._unmapped_from_row(row) for row in rows)

    def _get_mapping(self, mapping_id: str) -> ProviderFieldMapping | None:
        row = self._connection.execute(
            """
            SELECT mapping_id, mapping_version_id, provider_id, statement_type,
                   source_field, metric_code, method, formula, allowed_use_scopes
            FROM provider_field_mappings WHERE mapping_id = %s
            """,
            (mapping_id,),
        ).fetchone()
        return None if row is None else self._mapping_from_row(row)

    def _get_quality_rule(self, rule_id: str) -> FinancialQualityRule | None:
        row = self._connection.execute(
            """
            SELECT rule_id, name, rule_kind, terms, tolerance, severity
            FROM financial_quality_rules WHERE rule_id = %s
            """,
            (rule_id,),
        ).fetchone()
        return None if row is None else self._quality_rule_from_row(row)

    def _get_unmapped_field(self, unmapped_field_id: str) -> UnmappedProviderField | None:
        row = self._connection.execute(
            """
            SELECT unmapped_field_id, provider_id, statement_type, source_field,
                   mapping_version_id, discovered_at, raw_object_id, status,
                   resolved_mapping_id, resolution_reason
            FROM unmapped_metric_fields WHERE unmapped_field_id = %s
            """,
            (unmapped_field_id,),
        ).fetchone()
        return None if row is None else self._unmapped_from_row(row)

    @staticmethod
    def _metric_row(value: CanonicalMetric) -> tuple[object, ...]:
        return (
            value.metric_code,
            value.canonical_name,
            value.statement_type.value,
            value.unit.value,
            value.currency_requirement.value,
            value.sign_convention.value,
            value.description,
        )

    @staticmethod
    def _metric_from_row(row: Sequence[object]) -> CanonicalMetric:
        return CanonicalMetric(
            metric_code=str(row[0]),
            canonical_name=str(row[1]),
            statement_type=StatementType(str(row[2])),
            unit=MetricUnit(str(row[3])),
            currency_requirement=CurrencyRequirement(str(row[4])),
            sign_convention=SignConvention(str(row[5])),
            description=str(row[6]),
        )

    @staticmethod
    def _mapping_version_row(value: MappingVersion) -> tuple[object, ...]:
        return (
            value.mapping_version_id,
            value.provider_id,
            value.created_at,
            value.content_hash,
            value.code_version,
        )

    @staticmethod
    def _mapping_version_from_row(row: Sequence[object]) -> MappingVersion:
        return MappingVersion(
            mapping_version_id=str(row[0]),
            provider_id=str(row[1]),
            created_at=cast(datetime, row[2]),
            content_hash=str(row[3]),
            code_version=str(row[4]),
        )

    @staticmethod
    def _mapping_row(value: ProviderFieldMapping) -> tuple[object, ...]:
        return (
            value.mapping_id,
            value.mapping_version_id,
            value.provider_id,
            value.statement_type.value,
            value.source_field,
            value.metric_code,
            value.method.value,
            value.formula,
            sorted(scope.value for scope in value.allowed_use_scopes),
        )

    @staticmethod
    def _mapping_from_row(row: Sequence[object]) -> ProviderFieldMapping:
        raw_scopes = row[8]
        if not isinstance(raw_scopes, (list, tuple)):
            raise TypeError("stored mapping allowed_use_scopes must be an array")
        return ProviderFieldMapping(
            mapping_id=str(row[0]),
            mapping_version_id=str(row[1]),
            provider_id=str(row[2]),
            statement_type=StatementType(str(row[3])),
            source_field=str(row[4]),
            metric_code=str(row[5]),
            method=MappingMethod(str(row[6])),
            formula=None if row[7] is None else str(row[7]),
            allowed_use_scopes=frozenset(
                MappingUseScope(str(scope)) for scope in raw_scopes
            ),
        )

    @staticmethod
    def _quality_rule_from_row(row: Sequence[object]) -> FinancialQualityRule:
        raw_terms = _json_value(row[3])
        if not isinstance(raw_terms, list):
            raise TypeError("stored quality rule terms must be an array")
        terms: list[QualityTerm] = []
        for raw_term in raw_terms:
            if not isinstance(raw_term, Mapping):
                raise TypeError("stored quality rule term must be an object")
            terms.append(
                QualityTerm(
                    metric_code=str(raw_term["metric_code"]),
                    coefficient=Decimal(str(raw_term["coefficient"])),
                )
            )
        return FinancialQualityRule(
            rule_id=str(row[0]),
            name=str(row[1]),
            rule_kind=QualityRuleKind(str(row[2])),
            terms=tuple(terms),
            tolerance=Decimal(str(row[4])),
            severity=QualitySeverity(str(row[5])),
        )

    @staticmethod
    def _unmapped_row(value: UnmappedProviderField) -> tuple[object, ...]:
        return (
            value.unmapped_field_id,
            value.provider_id,
            value.statement_type.value,
            value.source_field,
            value.mapping_version_id,
            value.discovered_at,
            value.raw_object_id,
            value.status.value,
            value.resolved_mapping_id,
            value.resolution_reason,
        )

    @staticmethod
    def _unmapped_from_row(row: Sequence[object]) -> UnmappedProviderField:
        return UnmappedProviderField(
            unmapped_field_id=str(row[0]),
            provider_id=str(row[1]),
            statement_type=StatementType(str(row[2])),
            source_field=str(row[3]),
            mapping_version_id=str(row[4]),
            discovered_at=cast(datetime, row[5]),
            raw_object_id=str(row[6]),
            status=UnmappedFieldStatus(str(row[7])),
            resolved_mapping_id=None if row[8] is None else str(row[8]),
            resolution_reason=None if row[9] is None else str(row[9]),
        )


__all__ = ["PostgresMetricRegistryRepository"]
