import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.adapters.postgres.metrics import PostgresMetricRegistryRepository
from a_share_platform.application.metric_registry import MetricRegistryService
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

NOW = datetime(2026, 8, 11, 2, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def _json(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "obj"):
        return value.obj
    return value


def metric(metric_code: str = "total_assets") -> CanonicalMetric:
    return CanonicalMetric(
        metric_code=metric_code,
        canonical_name="Total Assets",
        statement_type=StatementType.BALANCE_SHEET,
        unit=MetricUnit.CURRENCY,
        currency_requirement=CurrencyRequirement.REQUIRED,
        sign_convention=SignConvention.NATURAL,
        description="Canonical total assets",
    )


def version() -> MappingVersion:
    return MappingVersion(
        mapping_version_id="mapping:factor-service-ths:v1",
        provider_id="factor_service_ths",
        created_at=NOW,
        content_hash=HASH,
        code_version="git:test",
    )


def mapping(
    *,
    method: MappingMethod = MappingMethod.EXACT,
    allowed_use_scopes: frozenset[MappingUseScope] = frozenset(
        {MappingUseScope.CURRENT_RESEARCH}
    ),
) -> ProviderFieldMapping:
    return ProviderFieldMapping(
        mapping_id="mapping:factor-service-ths:total-assets:v1",
        mapping_version_id=version().mapping_version_id,
        provider_id=version().provider_id,
        statement_type=StatementType.BALANCE_SHEET,
        source_field="ths_total_assets_stock",
        metric_code="total_assets",
        method=method,
        formula=("assets" if method is MappingMethod.FORMULA else None),
        allowed_use_scopes=allowed_use_scopes,
    )


def quality_rule() -> FinancialQualityRule:
    return FinancialQualityRule(
        rule_id="quality:balance-equation:v1",
        name="assets equal liabilities plus equity",
        rule_kind=QualityRuleKind.ACCOUNTING_IDENTITY,
        terms=(
            QualityTerm("total_assets", Decimal("1.000000000000000001")),
            QualityTerm("total_liabilities", Decimal(-1)),
        ),
        tolerance=Decimal("0.000000000000000001"),
        severity=QualitySeverity.BLOCK,
    )


def unmapped(
    identifier: str = "unmapped:factor-service:unknown:v1",
) -> UnmappedProviderField:
    return UnmappedProviderField(
        unmapped_field_id=identifier,
        provider_id=version().provider_id,
        statement_type=StatementType.BALANCE_SHEET,
        source_field="ths_unknown_stock",
        mapping_version_id=version().mapping_version_id,
        discovered_at=NOW,
        raw_object_id="raw:factor-service:batch-1",
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self) -> None:
        self.metrics: dict[str, tuple[object, ...]] = {}
        self.versions: dict[str, tuple[object, ...]] = {}
        self.mappings: dict[str, tuple[object, ...]] = {}
        self.rules: dict[str, tuple[object, ...]] = {}
        self.unmapped: dict[str, tuple[object, ...]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        sql = " ".join(query.split())
        if sql.startswith("INSERT INTO governance.canonical_metrics"):
            self.metrics.setdefault(str(params[0]), params)
        elif "FROM governance.canonical_metrics" in sql:
            row = self.metrics.get(str(params[0]))
            return FakeResult([] if row is None else [row])
        elif sql.startswith("INSERT INTO governance.metric_mapping_versions"):
            self.versions.setdefault(str(params[0]), params)
        elif "FROM governance.metric_mapping_versions" in sql:
            row = self.versions.get(str(params[0]))
            return FakeResult([] if row is None else [row])
        elif sql.startswith("INSERT INTO governance.provider_field_mappings"):
            self.mappings.setdefault(str(params[0]), params)
        elif "FROM governance.provider_field_mappings" in sql:
            if "WHERE mapping_id = %s" in sql:
                row = self.mappings.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            rows = [
                row
                for row in self.mappings.values()
                if row[2] == params[0]
                and row[3] == params[1]
                and row[4] == params[2]
                and row[1] == params[3]
            ]
            return FakeResult(sorted(rows, key=lambda row: str(row[0])))
        elif sql.startswith("INSERT INTO governance.financial_quality_rules"):
            self.rules.setdefault(
                str(params[0]),
                (*params[:3], _json(params[3]), *params[4:]),
            )
        elif "FROM governance.financial_quality_rules" in sql:
            row = self.rules.get(str(params[0]))
            return FakeResult([] if row is None else [row])
        elif sql.startswith("INSERT INTO governance.unmapped_metric_fields"):
            self.unmapped.setdefault(str(params[0]), params)
        elif "FROM governance.unmapped_metric_fields" in sql:
            if "WHERE unmapped_field_id = %s" in sql:
                row = self.unmapped.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            return FakeResult(
                sorted(
                    self.unmapped.values(),
                    key=lambda row: (str(row[7]), row[5], str(row[0])),
                )
            )
        return FakeResult()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class PostgresMetricRegistryRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()
        self.repository = PostgresMetricRegistryRepository(self.connection)

    def test_metric_and_mapping_version_are_append_only_and_round_trip(self) -> None:
        expected_metric = metric()
        expected_version = version()

        self.assertEqual(self.repository.register_metric(expected_metric), expected_metric)
        self.assertEqual(self.repository.get_metric(expected_metric.metric_code), expected_metric)
        self.assertEqual(
            self.repository.register_mapping_version(expected_version),
            expected_version,
        )
        self.assertEqual(
            self.repository.get_mapping_version(expected_version.mapping_version_id),
            expected_version,
        )
        self.assertEqual(self.repository.register_metric(expected_metric), expected_metric)
        with self.assertRaisesRegex(VersionConflictError, "immutable canonical metric"):
            self.repository.register_metric(
                replace(expected_metric, description="different definition")
            )
        with self.assertRaisesRegex(VersionConflictError, "immutable mapping version"):
            self.repository.register_mapping_version(
                replace(expected_version, code_version="git:different")
            )
        self.assertEqual(self.connection.commits, 0)
        self.assertEqual(self.connection.rollbacks, 0)

    def test_mapping_round_trip_preserves_formula_and_explicit_use_scopes(self) -> None:
        expected = mapping(
            method=MappingMethod.FORMULA,
            allowed_use_scopes=frozenset(
                {
                    MappingUseScope.CURRENT_RESEARCH,
                    MappingUseScope.STRICT_HISTORICAL,
                }
            ),
        )

        self.assertEqual(self.repository.register_mapping(expected), expected)
        self.assertEqual(
            self.repository.find_mappings(
                provider_id=expected.provider_id,
                statement_type=expected.statement_type,
                source_field=expected.source_field,
                mapping_version_id=expected.mapping_version_id,
            ),
            (expected,),
        )
        insert = next(
            params
            for query, params in self.connection.calls
            if "INSERT INTO governance.provider_field_mappings" in query
        )
        self.assertIsInstance(insert[8], list)
        self.assertEqual(
            insert[8],
            ["current_research", "strict_historical"],
        )
        self.assertEqual(
            self.repository.find_mappings(
                provider_id="other-provider",
                statement_type=expected.statement_type,
                source_field=expected.source_field,
                mapping_version_id=expected.mapping_version_id,
            ),
            (),
        )
        with self.assertRaisesRegex(VersionConflictError, "immutable provider mapping"):
            self.repository.register_mapping(
                replace(
                    expected,
                    allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH}),
                )
            )

    def test_quality_rule_round_trip_preserves_decimal_terms_and_tolerance(self) -> None:
        expected = quality_rule()

        restored = self.repository.register_quality_rule(expected)

        self.assertEqual(restored, expected)
        self.assertIsInstance(restored.tolerance, Decimal)
        self.assertEqual(restored.terms[0].coefficient, Decimal("1.000000000000000001"))
        insert = next(
            params
            for query, params in self.connection.calls
            if "INSERT INTO governance.financial_quality_rules" in query
        )
        terms = _json(insert[3])
        self.assertEqual(terms[0]["coefficient"], "1.000000000000000001")  # type: ignore[index]
        self.assertIsInstance(insert[4], Decimal)
        with self.assertRaisesRegex(VersionConflictError, "immutable quality rule"):
            self.repository.register_quality_rule(
                replace(expected, tolerance=Decimal("0.1"))
            )

    def test_unmapped_queue_is_append_only_ordered_and_never_fills_a_value(self) -> None:
        later = replace(
            unmapped("unmapped:later"),
            discovered_at=NOW.replace(hour=3),
        )
        ignored = replace(
            unmapped("unmapped:ignored"),
            status=UnmappedFieldStatus.IGNORED,
            resolution_reason="provider field is not an accounting value",
        )

        self.assertEqual(self.repository.enqueue_unmapped_field(later), later)
        self.assertEqual(self.repository.enqueue_unmapped_field(ignored), ignored)
        self.assertEqual(self.repository.list_unmapped_fields(), (ignored, later))
        with self.assertRaisesRegex(VersionConflictError, "immutable unmapped field"):
            self.repository.enqueue_unmapped_field(
                replace(later, source_field="different_field")
            )

    def test_application_service_can_use_the_complete_postgres_port(self) -> None:
        service = MetricRegistryService(self.repository)
        service.register_metric(metric())
        service.register_mapping_version(version())
        expected = service.register_mapping(mapping())

        selected = service.resolve_or_queue(
            provider_id=expected.provider_id,
            statement_type=expected.statement_type,
            source_field=expected.source_field,
            mapping_version_id=expected.mapping_version_id,
            use_scope=MappingUseScope.CURRENT_RESEARCH,
            unmapped_field_id="unmapped:not-used",
            discovered_at=NOW,
            raw_object_id="raw:not-used",
        )

        self.assertEqual(selected, expected)

    def test_repository_never_commits_updates_or_owns_the_outer_transaction(self) -> None:
        self.repository.register_metric(metric())
        self.repository.register_mapping_version(version())
        self.repository.register_mapping(mapping())
        self.repository.register_quality_rule(quality_rule())
        self.repository.enqueue_unmapped_field(unmapped())

        inserts = [query for query, _params in self.connection.calls if "INSERT INTO" in query]
        self.assertEqual(len(inserts), 5)
        self.assertTrue(all("ON CONFLICT DO NOTHING" in query for query in inserts))
        self.assertTrue(all("UPDATE" not in query and "DELETE" not in query for query in inserts))
        self.assertEqual(self.connection.commits, 0)
        self.assertEqual(self.connection.rollbacks, 0)


if __name__ == "__main__":
    unittest.main()
