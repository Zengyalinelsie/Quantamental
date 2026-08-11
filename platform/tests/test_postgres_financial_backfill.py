import json
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from a_share_platform.adapters.memory.metrics import InMemoryMetricRegistryRepository
from a_share_platform.adapters.postgres.financial_backfill import (
    PostgresCurrentKnownFinancialIdentityResolver,
    PostgresFinancialBackfillUnitOfWork,
    PostgresFinancialIdentityResolver,
)
from a_share_platform.application.financial_backfill import (
    FinancialBackfillMapper,
    FinancialBackfillPlanner,
)
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.backfill import BackfillCheckpointStatus, DatasetQualityStatus
from a_share_platform.domain.disclosure import RawObject, RawObjectKind, RetentionPolicy
from a_share_platform.domain.financial_backfill import (
    EMPTY_FINANCIAL_WORK_UNIT_WARNING,
    FinancialBackfillBatchResult,
    FinancialBackfillCohort,
    FinancialBackfillPlan,
    FinancialIdentityResolutionMethod,
    FinancialListingIdentity,
    FinancialProviderBatch,
    FinancialStatementSelection,
)
from a_share_platform.domain.financial_sources import (
    AvailabilityMethod,
    FinancialSourceAccessMode,
    FinancialSourceProfile,
    FinancialSourceQualification,
    FinancialSourceRole,
    FinancialStatementScope,
    FinancialValueBasis,
    ProviderFinancialRow,
    ReportVersionType,
)
from a_share_platform.domain.governance import LineageEdge
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
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType
from a_share_platform.domain.run_context import DataMode

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)
RAW_HASH = "sha256:" + "a" * 64


def _json(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "obj"):
        return value.obj
    return value


def plan() -> FinancialBackfillPlan:
    return FinancialBackfillPlan(
        plan_id="financial-backfill:csi300:2024:v1",
        provider_id="factor_service_ths",
        provider_profile_version="financial-source:factor-service-ths:v1",
        cohort=FinancialBackfillCohort.CSI_300,
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="mapping:factor-service-ths:v1",
        statements=(
            FinancialStatementSelection(StatementType.BALANCE_SHEET, "balance_sheet"),
        ),
        report_period_ends=(date(2024, 12, 31),),
        symbols=("SH.600000",),
        symbol_bucket_size=1,
        created_at=NOW,
        data_mode=DataMode.CURRENT_RESEARCH,
        output_trust_state=DataTrustState.NORMALIZED_CURRENT,
        allow_read_through_cache=True,
        bulk_persistence_acknowledged=True,
    )


def profile() -> FinancialSourceProfile:
    return FinancialSourceProfile(
        profile_version="financial-source:factor-service-ths:v1",
        provider_id="factor_service_ths",
        role=FinancialSourceRole.PRIMARY,
        markets=frozenset({"XSHG", "XSHE"}),
        statements=frozenset(StatementType),
        access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
        qualification=FinancialSourceQualification.NORMALIZED_CURRENT_APPROVED,
        trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
        retention_allowed=True,
        bulk_persistence_allowed=True,
        supplies_revision_history=False,
        supplies_exact_available_at=False,
        max_rows_per_request=5000,
        warnings=(),
    )


def mapping_result(*, retrieved_at: datetime = NOW):  # type: ignore[no-untyped-def]
    evidence = RawObject(
        raw_object_id="raw:factor-service:balance-sheet:batch-1",
        object_kind=RawObjectKind.FILE,
        content_hash=RAW_HASH,
        source_url="https://factor.example.internal/api/v2/table/query",
        provider_id="factor_service_ths",
        retrieved_at=retrieved_at,
        media_type="application/vnd.a-share-platform.http-exchange-manifest+json",
        storage_uri="file:///private/research/evidence/batch-1.json",
        license_id="license:private-local-research-test",
        retention_policy=RetentionPolicy.INDEFINITE,
        retention_until=None,
        redistribution_allowed=False,
    )
    work_unit = FinancialBackfillPlanner().preview(plan(), profile()).work_units[0]
    provider_row = ProviderFinancialRow(
        row_id="provider-row:factor-service:600000:2024:total-assets",
        provider_id="factor_service_ths",
        provider_table="balance_sheet",
        provider_record_id="factor-service-row:600000:2024",
        provider_field="ths_total_assets_stock",
        market="XSHG",
        source_symbol="600000",
        statement_type=StatementType.BALANCE_SHEET,
        statement_scope=FinancialStatementScope.UNKNOWN,
        report_period_start=date(2024, 12, 31),
        report_period_end=date(2024, 12, 31),
        period_type=FinancialPeriodType.ANNUAL,
        value_basis=FinancialValueBasis.POINT_IN_TIME,
        raw_value=Decimal("123.450000000000000001"),
        provider_unit="CNY_10K",
        scale_to_canonical=Decimal(10000),
        currency="CNY",
        report_version_type=ReportVersionType.UNKNOWN,
        revision_sequence=0,
        announced_at=None,
        available_at=retrieved_at,
        availability_method=AvailabilityMethod.CONSERVATIVE_RETRIEVAL_TIME,
        provider_updated_at=None,
        retrieved_at=retrieved_at,
        raw_object_id=evidence.raw_object_id,
        raw_object_hash=evidence.content_hash,
        source_url=evidence.source_url,
        warnings=("provider revision semantics unavailable",),
    )
    batch = FinancialProviderBatch(
        work_unit=work_unit,
        evidence=evidence,
        rows=(provider_row,),
        provider_record_count=1,
        missing_value_count=0,
        accepted_symbols=("SH.600000",),
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        warnings=("current-only provider response",),
    )
    repository = InMemoryMetricRegistryRepository()
    service = MetricRegistryService(repository)
    service.register_metric(
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
    service.register_mapping_version(
        MappingVersion(
            mapping_version_id="mapping:factor-service-ths:v1",
            provider_id="factor_service_ths",
            created_at=NOW,
            content_hash="sha256:" + "b" * 64,
            code_version="git:test",
        )
    )
    service.register_mapping(
        ProviderFieldMapping(
            mapping_id="mapping:factor-service-ths:total-assets:v1",
            mapping_version_id="mapping:factor-service-ths:v1",
            provider_id="factor_service_ths",
            statement_type=StatementType.BALANCE_SHEET,
            source_field="ths_total_assets_stock",
            metric_code="total_assets",
            method=MappingMethod.EXACT,
            formula=None,
            allowed_use_scopes=frozenset({MappingUseScope.CURRENT_RESEARCH}),
        )
    )
    return FinancialBackfillMapper(repository).map(
        batch,
        data_mode=DataMode.CURRENT_RESEARCH,
    )


def empty_mapping_result():  # type: ignore[no-untyped-def]
    populated = mapping_result()
    batch = replace(
        populated.provider_batch,
        rows=(),
        provider_record_count=0,
        missing_value_count=0,
        accepted_symbols=(),
        warnings=("requested report period is unavailable",),
    )
    return replace(
        populated,
        provider_batch=batch,
        mapped_rows=(),
        unmapped_row_ids=(),
        warnings=(),
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class PersistingFakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.raw_row: tuple[object, ...] | None = None
        self.dataset_row: tuple[object, ...] | None = None
        self.observation_row: tuple[object, ...] | None = None
        self.receipt_row: tuple[object, ...] | None = None
        self.work_unit_row: tuple[object, ...] | None = None
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        sql = " ".join(query.split())
        if sql.startswith("INSERT INTO evidence.raw_objects"):
            self.raw_row = params
        elif "FROM evidence.raw_objects" in sql:
            return FakeResult([] if self.raw_row is None else [self.raw_row])
        elif sql.startswith("INSERT INTO governance.dataset_versions"):
            self.dataset_row = (*params[:4], _json(params[4]))
        elif "FROM governance.dataset_versions" in sql:
            return FakeResult([] if self.dataset_row is None else [self.dataset_row])
        elif sql.startswith("INSERT INTO governance.financial_backfill_work_units"):
            self.work_unit_row = (*params[:12], _json(params[12]), params[13])
        elif "FROM governance.financial_backfill_work_units" in sql:
            return FakeResult(
                [] if self.work_unit_row is None else [self.work_unit_row]
            )
        elif sql.startswith("INSERT INTO observation.normalized_current_financial_observations"):
            self.observation_row = params
        elif "FROM observation.normalized_current_financial_observations" in sql:
            return FakeResult(
                [] if self.observation_row is None else [self.observation_row]
            )
        elif sql.startswith("INSERT INTO governance.financial_backfill_persist_receipts"):
            self.receipt_row = params
        elif "FROM governance.financial_backfill_persist_receipts" in sql:
            if self.receipt_row is None:
                return FakeResult()
            return FakeResult(
                [
                    (
                        self.receipt_row[2],
                        _json(self.receipt_row[4]),
                        _json(self.receipt_row[5]),
                        self.receipt_row[8],
                    )
                ]
            )
        return FakeResult()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class StubIdentityResolver:
    resolution_method = (
        FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def resolve(self, canonical_symbol: str, *, as_of: date) -> FinancialListingIdentity:
        self.calls.append((canonical_symbol, as_of))
        return FinancialListingIdentity(
            canonical_symbol=canonical_symbol,
            company_id="company:600000",
            security_id="security:600000:XSHG",
            listing_id="listing:600000:XSHG",
            resolved_as_of=as_of,
        )


class PostgresFinancialIdentityResolverTest(unittest.TestCase):
    def test_resolves_stable_ids_from_effective_dated_security_master_only(self) -> None:
        class Connection:
            def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
                self.query = query
                self.params = params
                return FakeResult(
                    [("company:600000", "security:600000:XSHG", "listing:600000:XSHG")]
                )

        connection = Connection()
        resolver = PostgresFinancialIdentityResolver(connection)  # type: ignore[arg-type]

        identity = resolver.resolve("SH.600000", as_of=date(2024, 12, 31))

        self.assertEqual(identity.company_id, "company:600000")
        self.assertIn("identifier_history", connection.query)
        self.assertEqual(
            connection.params,
            (
                "XSHG",
                "600000",
                date(2024, 12, 31),
                date(2024, 12, 31),
                date(2024, 12, 31),
                date(2024, 12, 31),
            ),
        )

    def test_delisting_date_is_inclusive_and_the_following_day_is_unresolved(self) -> None:
        delisted_on = date(2024, 12, 31)

        class Connection:
            def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
                self.query = query
                as_of = params[-1]
                if not isinstance(as_of, date):
                    raise TypeError("as_of must be a date")
                if as_of <= delisted_on:
                    return FakeResult([("company:1", "security:1", "listing:1")])
                return FakeResult()

        connection = Connection()
        resolver = PostgresFinancialIdentityResolver(connection)  # type: ignore[arg-type]

        self.assertEqual(
            resolver.resolve("SH.600000", as_of=delisted_on).listing_id,
            "listing:1",
        )
        self.assertIn("%s <= listings.delisted_on", connection.query)
        with self.assertRaisesRegex(LookupError, "unresolved"):
            resolver.resolve("SH.600000", as_of=date(2025, 1, 1))

    def test_missing_or_ambiguous_identity_fails_closed(self) -> None:
        class Connection:
            def __init__(self, rows: list[tuple[object, ...]]) -> None:
                self.rows = rows

            def execute(self, *_args: object, **_kwargs: object) -> FakeResult:
                return FakeResult(self.rows)

        for rows, expected in (([], "unresolved"), ([("c1", "s1", "l1"), ("c2", "s2", "l2")], "ambiguous")):
            with self.subTest(expected=expected):
                resolver = PostgresFinancialIdentityResolver(Connection(rows))  # type: ignore[arg-type]
                with self.assertRaisesRegex(LookupError, expected):
                    resolver.resolve("SH.600000", as_of=date(2024, 12, 31))

    def test_current_known_resolver_is_separate_and_uses_the_supplied_retrieval_date(
        self,
    ) -> None:
        class Connection:
            def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
                self.query = query
                self.params = params
                return FakeResult(
                    [("company:600000", "security:600000:XSHG", "listing:600000:XSHG")]
                )

        connection = Connection()
        resolver = PostgresCurrentKnownFinancialIdentityResolver(connection)  # type: ignore[arg-type]
        retrieval_date = NOW.date()

        identity = resolver.resolve("SH.600000", as_of=retrieval_date)

        self.assertEqual(
            resolver.resolution_method,
            FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE,
        )
        self.assertEqual(identity.resolved_as_of, retrieval_date)
        self.assertIn("identifier_history", connection.query)
        self.assertEqual(connection.params[-1], retrieval_date)


class PostgresFinancialBackfillUnitOfWorkTest(unittest.TestCase):
    def test_normalized_current_uow_rejects_the_strict_effective_dated_resolver(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "current-known"):
            PostgresFinancialBackfillUnitOfWork(
                PersistingFakeConnection(),
                job_id="job:financial:csi300:2024:v1",
                identity_resolver=PostgresFinancialIdentityResolver(
                    PersistingFakeConnection()
                ),
            )

    def test_checkpoint_reports_lineage_and_transaction_boundaries_are_durable(self) -> None:
        result = mapping_result()
        unit = result.provider_batch.work_unit
        planner = FinancialBackfillPlanner()
        pending = planner.pending_checkpoint(
            job_id="job:financial:csi300:2024:v1",
            unit=unit,
            at=NOW,
        )
        running = pending.transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        batch_result = FinancialBackfillBatchResult(
            work_unit=unit,
            retrieved_at=NOW,
            provider_cutoff_date=NOW.date(),
            content_hash=RAW_HASH,
            processed_provider_rows=1,
            canonical_observations=1,
            rejected_rows=0,
            accepted_symbols=("SH.600000",),
            quality_status=DatasetQualityStatus.PASSED,
            issue_counts=(),
            warnings=("normalized_current only",),
        )
        succeeded = planner.complete_checkpoint(running, result=batch_result, at=NOW)
        quality, coverage = planner.build_reports(
            job_id=succeeded.job_id,
            dataset_version_id="dataset:financial:test",
            result=batch_result,
            created_at=NOW,
        )
        connection = PersistingFakeConnection()
        uow = PostgresFinancialBackfillUnitOfWork(
            connection,
            job_id=succeeded.job_id,
            identity_resolver=StubIdentityResolver(),
        )

        uow.save_checkpoint(succeeded)
        uow.save_quality_report(quality)
        uow.save_coverage_report(coverage)
        uow.register_lineage(LineageEdge("raw:upstream", "dataset:financial:test", "evidence_for"))
        uow.commit()
        uow.rollback()

        checkpoint_params = next(
            params
            for query, params in connection.calls
            if "INSERT INTO governance.ingestion_checkpoints" in query
        )
        self.assertEqual(checkpoint_params[3], "financial_statement")
        self.assertEqual(checkpoint_params[15], "not_applicable")
        self.assertTrue(any("INSERT INTO governance.dataset_quality_reports" in q for q, _ in connection.calls))
        self.assertTrue(any("INSERT INTO governance.dataset_coverage_reports" in q for q, _ in connection.calls))
        self.assertTrue(any("INSERT INTO governance.lineage_edges" in q for q, _ in connection.calls))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 1)

    def test_persist_is_lossless_current_only_and_returns_a_durable_receipt(self) -> None:
        connection = PersistingFakeConnection()
        resolver = StubIdentityResolver()
        uow = PostgresFinancialBackfillUnitOfWork(
            connection,
            job_id="job:financial:csi300:2024:v1",
            identity_resolver=resolver,
        )

        receipt = uow.persist(mapping_result())

        self.assertEqual(resolver.calls, [("SH.600000", NOW.date())])
        self.assertEqual(
            receipt.identity_resolution_method,
            FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE,
        )
        self.assertEqual(len(receipt.observation_ids), 1)
        self.assertEqual(
            uow.get_persist_result(
                "job:financial:csi300:2024:v1",
                mapping_result().provider_batch.work_unit.checkpoint_key,
            ),
            receipt,
        )
        observation_call = next(
            call
            for call in connection.calls
            if "INSERT INTO observation.normalized_current_financial_observations" in call[0]
        )
        query, params = observation_call
        self.assertIn("ON CONFLICT (observation_id) DO NOTHING", query)
        self.assertNotIn("UPDATE", query)
        self.assertIn(Decimal("123.450000000000000001"), params)
        self.assertIn(Decimal("1234500.000000000000010000"), params)
        self.assertIn("unknown", params)
        self.assertIn("point_in_time", params)
        self.assertIn("normalized_current", params)
        self.assertIn("current_known_retrieval_date", params)
        self.assertNotIn("pit_verified", params)
        warning_values = tuple(str(value) for value in _json(params[-1]))
        self.assertTrue(
            any("current-known" in value for value in warning_values),
            warning_values,
        )

        receipt_params = next(
            params
            for query, params in connection.calls
            if "INSERT INTO governance.financial_backfill_persist_receipts" in query
        )
        self.assertEqual(_json(receipt_params[4]), list(receipt.observation_ids))
        self.assertEqual(receipt_params[6], "normalized_current")
        self.assertTrue(
            any("current-known" in warning for warning in _json(receipt_params[5]))
        )
        self.assertIn("current_known_retrieval_date", receipt_params)

        dataset_metadata = connection.dataset_row[4]  # type: ignore[index]
        self.assertIsInstance(dataset_metadata, dict)
        manifest = dataset_metadata["manifest"]  # type: ignore[index]
        self.assertEqual(
            manifest["identity_resolution_method"],  # type: ignore[index]
            "current_known_retrieval_date",
        )
        self.assertTrue(
            any("current-known" in warning for warning in manifest["warnings"])  # type: ignore[index]
        )
        self.assertEqual(
            manifest["rows"][0]["identity_as_of"],  # type: ignore[index]
            NOW.date().isoformat(),
        )

    def test_empty_period_persists_evidence_dataset_work_unit_and_zero_receipt(self) -> None:
        connection = PersistingFakeConnection()
        resolver = StubIdentityResolver()
        uow = PostgresFinancialBackfillUnitOfWork(
            connection,
            job_id="job:financial:csi300:2024:v1",
            identity_resolver=resolver,
        )

        receipt = uow.persist(empty_mapping_result())

        self.assertEqual(receipt.observation_ids, ())
        self.assertEqual(
            receipt.identity_resolution_method,
            FinancialIdentityResolutionMethod.NO_OBSERVATIONS,
        )
        self.assertIn(EMPTY_FINANCIAL_WORK_UNIT_WARNING, receipt.warnings)
        self.assertEqual(resolver.calls, [])
        self.assertIsNotNone(connection.raw_row)
        self.assertIsNotNone(connection.dataset_row)
        self.assertIsNotNone(connection.work_unit_row)
        self.assertIsNotNone(connection.receipt_row)
        assert connection.receipt_row is not None
        self.assertEqual(connection.receipt_row[3], 0)
        self.assertEqual(_json(connection.receipt_row[4]), [])
        self.assertIsNone(connection.observation_row)
        assert connection.dataset_row is not None
        metadata = _json(connection.dataset_row[4])
        self.assertIsInstance(metadata, dict)
        manifest = metadata["manifest"]  # type: ignore[index]
        self.assertEqual(manifest["rows"], [])  # type: ignore[index]
        self.assertEqual(
            manifest["identity_resolution_method"],  # type: ignore[index]
            "no_observations",
        )

    def test_nonempty_unmapped_rows_cannot_use_the_no_observations_receipt(self) -> None:
        populated = mapping_result()
        unmapped = replace(
            populated,
            mapped_rows=(),
            unmapped_row_ids=(populated.provider_batch.rows[0].row_id,),
        )
        connection = PersistingFakeConnection()
        uow = PostgresFinancialBackfillUnitOfWork(
            connection,
            job_id="job:financial:csi300:2024:v1",
            identity_resolver=StubIdentityResolver(),
        )

        with self.assertRaisesRegex(ValueError, "provider rows but no mapped"):
            uow.persist(unmapped)

        self.assertIsNone(connection.dataset_row)
        self.assertIsNone(connection.receipt_row)

    def test_current_identity_date_uses_utc_across_a_shanghai_midnight(self) -> None:
        shanghai = timezone(timedelta(hours=8))
        retrieved_at = datetime(2026, 8, 11, 0, 30, tzinfo=shanghai)
        expected_utc_date = date(2026, 8, 10)
        connection = PersistingFakeConnection()
        resolver = StubIdentityResolver()
        uow = PostgresFinancialBackfillUnitOfWork(
            connection,
            job_id="job:financial:csi300:2024:v1",
            identity_resolver=resolver,
        )

        receipt = uow.persist(mapping_result(retrieved_at=retrieved_at))

        self.assertEqual(resolver.calls, [("SH.600000", expected_utc_date)])
        self.assertEqual(
            receipt.identity_resolution_method,
            FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE,
        )
        manifest = connection.dataset_row[4]["manifest"]  # type: ignore[index]
        self.assertEqual(
            manifest["rows"][0]["identity_as_of"],  # type: ignore[index]
            expected_utc_date.isoformat(),
        )

    def test_unresolved_identity_aborts_before_financial_or_dataset_inserts(self) -> None:
        class MissingIdentity:
            resolution_method = (
                FinancialIdentityResolutionMethod.CURRENT_KNOWN_RETRIEVAL_DATE
            )

            def resolve(self, *_args: object, **_kwargs: object) -> FinancialListingIdentity:
                raise LookupError("unresolved financial identity")

        connection = PersistingFakeConnection()
        uow = PostgresFinancialBackfillUnitOfWork(
            connection,
            job_id="job:financial:csi300:2024:v1",
            identity_resolver=MissingIdentity(),
        )

        with self.assertRaisesRegex(LookupError, "unresolved"):
            uow.persist(mapping_result())

        self.assertFalse(
            any(
                "dataset_versions" in query
                or "normalized_current_financial_observations" in query
                for query, _params in connection.calls
            )
        )

    def test_migration_preserves_every_financial_dimension_and_receipt(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0018_normalized_current_financial_backfill.sql"
        ).read_text(encoding="utf-8")
        normalized = " ".join(sql.split())
        for contract in (
            "CREATE TABLE normalized_current_financial_observations",
            "raw_value NUMERIC",
            "scale_to_canonical NUMERIC",
            "canonical_value NUMERIC",
            "statement_scope",
            "report_period_start",
            "value_basis",
            "report_version_type",
            "provider_record_id",
            "availability_method",
            "trust_state = 'normalized_current'",
            "CREATE TABLE financial_backfill_persist_receipts",
            "observation_ids JSONB",
            "CREATE TRIGGER normalized_current_financial_observations_append_only",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized)


if __name__ == "__main__":
    unittest.main()
