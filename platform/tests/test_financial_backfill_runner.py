import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.adapters.memory.metrics import InMemoryMetricRegistryRepository
from a_share_platform.application.financial_backfill import (
    FinancialBackfillBlockedError,
    FinancialBackfillMapper,
    FinancialBackfillPlanner,
    FinancialBackfillRunner,
)
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    DatasetCoverageReport,
    DatasetQualityReport,
)
from a_share_platform.domain.disclosure import RawObject, RawObjectKind, RetentionPolicy
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillCohort,
    FinancialBackfillPlan,
    FinancialMappingResult,
    FinancialPersistResult,
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

NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


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


def raw_object() -> RawObject:
    return RawObject(
        raw_object_id="raw:factor-service:batch-1",
        object_kind=RawObjectKind.RESPONSE,
        content_hash=HASH,
        source_url="https://factor.example.internal/api/v2/table/query",
        provider_id="factor_service_ths",
        retrieved_at=NOW,
        media_type="application/json",
        storage_uri="memory://factor-service/batch-1",
        license_id="license:private-local-research-test",
        retention_policy=RetentionPolicy.INDEFINITE,
        retention_until=None,
        redistribution_allowed=False,
    )


def provider_batch():
    work_unit = FinancialBackfillPlanner().preview(plan(), profile()).work_units[0]
    row = ProviderFinancialRow(
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
        raw_value=Decimal("123.45"),
        provider_unit="CNY_10K",
        scale_to_canonical=Decimal(10000),
        currency="CNY",
        report_version_type=ReportVersionType.UNKNOWN,
        revision_sequence=0,
        announced_at=None,
        available_at=NOW,
        availability_method=AvailabilityMethod.CONSERVATIVE_RETRIEVAL_TIME,
        provider_updated_at=None,
        retrieved_at=NOW,
        raw_object_id=raw_object().raw_object_id,
        raw_object_hash=HASH,
        source_url=raw_object().source_url,
        warnings=("provider revision semantics unavailable",),
    )
    return FinancialProviderBatch(
        work_unit=work_unit,
        evidence=raw_object(),
        rows=(row,),
        provider_record_count=1,
        missing_value_count=0,
        accepted_symbols=("SH.600000",),
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        warnings=("current-only provider response",),
    )


def mapper(
    *,
    allowed_use_scopes: frozenset[MappingUseScope] = frozenset(
        {MappingUseScope.CURRENT_RESEARCH}
    ),
) -> tuple[FinancialBackfillMapper, InMemoryMetricRegistryRepository]:
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
            allowed_use_scopes=allowed_use_scopes,
        )
    )
    return FinancialBackfillMapper(repository), repository


class FinancialBackfillMapperTest(unittest.TestCase):
    def test_explicit_mapping_preserves_decimal_evidence_and_current_trust(self) -> None:
        value, _repository = mapper()
        result = value.map(
            provider_batch(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        mapped = result.mapped_rows[0]
        self.assertEqual(mapped.value, Decimal("1234500.00"))
        self.assertEqual(mapped.metric_code, "total_assets")
        self.assertEqual(mapped.raw_object_id, raw_object().raw_object_id)
        self.assertEqual(mapped.trust_state, DataTrustState.NORMALIZED_CURRENT)

    def test_unmapped_field_is_queued_and_not_converted_to_zero(self) -> None:
        value, repository = mapper()
        batch = provider_batch()
        unknown = replace(batch.rows[0], provider_field="unknown_field")
        result = value.map(
            replace(batch, rows=(unknown,)),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertEqual(result.mapped_rows, ())
        self.assertEqual(result.unmapped_row_ids, (unknown.row_id,))
        self.assertEqual(len(repository.list_unmapped_fields()), 1)

    def test_production_only_mapping_does_not_authorize_current_backfill(self) -> None:
        value, _repository = mapper(
            allowed_use_scopes=frozenset({MappingUseScope.PRODUCTION})
        )
        with self.assertRaisesRegex(PermissionError, "current_research"):
            value.map(
                provider_batch(),
                data_mode=DataMode.CURRENT_RESEARCH,
            )

    def test_mapping_result_cannot_silently_drop_a_provider_row(self) -> None:
        batch = provider_batch()

        with self.assertRaisesRegex(ValueError, "classified"):
            FinancialMappingResult(
                provider_batch=batch,
                mapped_rows=(),
                unmapped_row_ids=(),
                warnings=(),
            )


class StubSource:
    provider_id = "factor_service_ths"

    def __init__(self, batch: FinancialProviderBatch) -> None:
        self.batch = batch
        self.calls = 0

    def fetch(self, *_args: object, **_kwargs: object) -> FinancialProviderBatch:
        self.calls += 1
        return self.batch


class FailingSource(StubSource):
    def fetch(self, *_args: object, **_kwargs: object) -> FinancialProviderBatch:
        self.calls += 1
        raise RuntimeError("provider unavailable")


class MemoryUnitOfWork:
    def __init__(self) -> None:
        self.checkpoints: dict[tuple[str, str], BackfillCheckpoint] = {}
        self.quality: list[DatasetQualityReport] = []
        self.coverage: list[DatasetCoverageReport] = []
        self.lineage: list[LineageEdge] = []
        self.persisted = []
        self.persist_result: FinancialPersistResult | None = None
        self.commits = 0
        self.rollbacks = 0

    def get_checkpoint(self, job_id: str, checkpoint_key: str):  # type: ignore[no-untyped-def]
        return self.checkpoints.get((job_id, checkpoint_key))

    def save_checkpoint(self, value: BackfillCheckpoint) -> BackfillCheckpoint:
        self.checkpoints[(value.job_id, value.checkpoint_key)] = value
        return value

    def persist(self, value):  # type: ignore[no-untyped-def]
        self.persisted.append(value)
        self.persist_result = FinancialPersistResult(
            dataset_version_id="dataset:financial:csi300:2024:v1",
            observation_ids=("observation:total-assets:600000:2024",),
            warnings=(),
        )
        return self.persist_result

    def get_persist_result(self, _job_id: str, _checkpoint_key: str):  # type: ignore[no-untyped-def]
        return self.persist_result

    def save_quality_report(self, value: DatasetQualityReport) -> DatasetQualityReport:
        self.quality.append(value)
        return value

    def save_coverage_report(self, value: DatasetCoverageReport) -> DatasetCoverageReport:
        self.coverage.append(value)
        return value

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        self.lineage.append(value)
        return value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FinancialBackfillRunnerTest(unittest.TestCase):
    def test_runner_closes_checkpoint_reports_and_raw_mapping_universe_lineage(self) -> None:
        source = StubSource(provider_batch())
        unit_of_work = MemoryUnitOfWork()
        value, _repository = mapper()
        runner = FinancialBackfillRunner(
            planner=FinancialBackfillPlanner(),
            mapper=value,
            unit_of_work=unit_of_work,
            clock=lambda: NOW,
        )
        work_unit = source.batch.work_unit

        outcome = runner.run_unit(
            plan=plan(),
            profile=profile(),
            job_id="job:financial:csi300:2024:v1",
            work_unit=work_unit,
            source=source,
        )

        self.assertFalse(outcome.skipped)
        self.assertEqual(outcome.checkpoint.status, BackfillCheckpointStatus.SUCCEEDED)
        self.assertEqual(outcome.dataset_version_id, "dataset:financial:csi300:2024:v1")
        self.assertEqual(len(unit_of_work.quality), 1)
        self.assertEqual(len(unit_of_work.coverage), 1)
        lineage = {(item.upstream_id, item.downstream_id, item.relation) for item in unit_of_work.lineage}
        self.assertIn(
            (raw_object().raw_object_id, outcome.dataset_version_id, "evidence_for"),
            lineage,
        )
        self.assertIn((plan().mapping_version_id, outcome.dataset_version_id, "mapped_by"), lineage)
        self.assertIn((plan().universe_version_id, outcome.dataset_version_id, "scoped_by"), lineage)
        self.assertEqual(source.calls, 1)

    def test_provider_failure_rolls_back_unit_and_durably_marks_checkpoint_failed(self) -> None:
        source = FailingSource(provider_batch())
        unit_of_work = MemoryUnitOfWork()
        value, _repository = mapper()
        runner = FinancialBackfillRunner(
            planner=FinancialBackfillPlanner(),
            mapper=value,
            unit_of_work=unit_of_work,
            clock=lambda: NOW,
        )
        with self.assertRaisesRegex(RuntimeError, "provider unavailable"):
            runner.run_unit(
                plan=plan(),
                profile=profile(),
                job_id="job:financial:csi300:2024:v1",
                work_unit=source.batch.work_unit,
                source=source,
            )
        checkpoint = unit_of_work.get_checkpoint(
            "job:financial:csi300:2024:v1",
            source.batch.work_unit.checkpoint_key,
        )
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.status, BackfillCheckpointStatus.FAILED)  # type: ignore[union-attr]
        self.assertEqual(unit_of_work.rollbacks, 1)
        self.assertEqual(unit_of_work.persisted, [])

    def test_succeeded_checkpoint_skips_provider_and_mapping_on_resume(self) -> None:
        source = StubSource(provider_batch())
        unit_of_work = MemoryUnitOfWork()
        value, _repository = mapper()
        runner = FinancialBackfillRunner(
            planner=FinancialBackfillPlanner(),
            mapper=value,
            unit_of_work=unit_of_work,
            clock=lambda: NOW,
        )
        pending = FinancialBackfillPlanner.pending_checkpoint(
            job_id="job:financial:csi300:2024:v1",
            unit=source.batch.work_unit,
            at=NOW,
        )
        running = pending.transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        succeeded = running.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=NOW,
            processed_rows=1,
            rejected_rows=0,
            content_hash=HASH,
        )
        unit_of_work.save_checkpoint(succeeded)
        unit_of_work.persist_result = FinancialPersistResult(
            dataset_version_id="dataset:financial:csi300:2024:v1",
            observation_ids=("observation:total-assets:600000:2024",),
            warnings=(),
        )

        outcome = runner.run_unit(
            plan=plan(),
            profile=profile(),
            job_id="job:financial:csi300:2024:v1",
            work_unit=source.batch.work_unit,
            source=source,
        )

        self.assertTrue(outcome.skipped)
        self.assertEqual(source.calls, 0)
        self.assertEqual(unit_of_work.persisted, [])

    def test_succeeded_checkpoint_without_persist_receipt_fails_closed(self) -> None:
        source = StubSource(provider_batch())
        unit_of_work = MemoryUnitOfWork()
        value, _repository = mapper()
        runner = FinancialBackfillRunner(
            planner=FinancialBackfillPlanner(),
            mapper=value,
            unit_of_work=unit_of_work,
            clock=lambda: NOW,
        )
        pending = FinancialBackfillPlanner.pending_checkpoint(
            job_id="job:financial:csi300:2024:v1",
            unit=source.batch.work_unit,
            at=NOW,
        )
        running = pending.transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        succeeded = running.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=NOW,
            processed_rows=1,
            content_hash=HASH,
        )
        unit_of_work.save_checkpoint(succeeded)

        with self.assertRaisesRegex(RuntimeError, "persist result"):
            runner.run_unit(
                plan=plan(),
                profile=profile(),
                job_id="job:financial:csi300:2024:v1",
                work_unit=source.batch.work_unit,
                source=source,
            )

        self.assertEqual(source.calls, 0)

    def test_candidate_is_blocked_before_checkpoint_or_source_access(self) -> None:
        source = StubSource(provider_batch())
        unit_of_work = MemoryUnitOfWork()
        value, _repository = mapper()
        runner = FinancialBackfillRunner(
            planner=FinancialBackfillPlanner(),
            mapper=value,
            unit_of_work=unit_of_work,
            clock=lambda: NOW,
        )
        candidate = replace(
            profile(),
            qualification=FinancialSourceQualification.CANDIDATE,
        )
        with self.assertRaises(FinancialBackfillBlockedError):
            runner.run_unit(
                plan=plan(),
                profile=candidate,
                job_id="job:financial:csi300:2024:v1",
                work_unit=source.batch.work_unit,
                source=source,
            )
        self.assertEqual(source.calls, 0)
        self.assertEqual(unit_of_work.checkpoints, {})


if __name__ == "__main__":
    unittest.main()
