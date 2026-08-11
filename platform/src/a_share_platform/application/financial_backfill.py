"""Read-only planning and ledger projection for P3.5 financial scale-up."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    BackfillDataDomain,
    BackfillQualification,
    DatasetCoverageReport,
    DatasetQualityReport,
    DatasetQualityStatus,
    ProviderRetrievalMetadata,
)
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillBatchResult,
    FinancialBackfillPlan,
    FinancialBackfillWorkUnit,
    FinancialMappingResult,
    FinancialProviderBatch,
    MappedFinancialRow,
)
from a_share_platform.domain.financial_sources import (
    FinancialSourcePermissionError,
    FinancialSourceProfile,
)
from a_share_platform.domain.governance import LineageEdge
from a_share_platform.domain.metrics import (
    MappingMethod,
    MappingUseScope,
    MetricUnit,
    UnmappedProviderField,
)
from a_share_platform.domain.run_context import DataMode
from a_share_platform.ports.financial_backfill import (
    FinancialBackfillSource,
    FinancialBackfillUnitOfWork,
)
from a_share_platform.ports.metrics import MetricRegistryRepository


class FinancialBackfillBlockedError(PermissionError):
    """The immutable plan/profile pair is not qualified for execution."""


@dataclass(frozen=True)
class FinancialBackfillRunOutcome:
    checkpoint: BackfillCheckpoint
    dataset_version_id: str | None
    observation_ids: tuple[str, ...]
    skipped: bool


class FinancialBackfillMapper:
    """Resolve explicit versioned mappings without losing Decimal/evidence semantics."""

    def __init__(self, repository: MetricRegistryRepository) -> None:
        self._repository = repository

    def map(
        self,
        batch: FinancialProviderBatch,
        *,
        data_mode: DataMode,
    ) -> FinancialMappingResult:
        data_mode = DataMode(data_mode)
        if data_mode is not DataMode.CURRENT_RESEARCH:
            raise PermissionError(
                "normalized_current financial backfill cannot use strict_historical"
            )
        version = self._repository.get_mapping_version(batch.work_unit.mapping_version_id)
        if version is None:
            raise ValueError(
                f"mapping version does not exist: {batch.work_unit.mapping_version_id}"
            )
        if version.provider_id != batch.work_unit.provider_id:
            raise ValueError("mapping version provider does not match financial work unit")
        mapped_rows: list[MappedFinancialRow] = []
        unmapped_ids: list[str] = []
        for row in batch.rows:
            mappings = self._repository.find_mappings(
                provider_id=row.provider_id,
                statement_type=row.statement_type,
                source_field=row.provider_field,
                mapping_version_id=batch.work_unit.mapping_version_id,
            )
            if len(mappings) > 1:
                raise ValueError("multiple mappings match one provider financial field")
            if not mappings:
                unmapped_digest = hashlib.sha256(
                    f"{row.row_id}|{batch.work_unit.mapping_version_id}".encode()
                ).hexdigest()[:24]
                self._repository.enqueue_unmapped_field(
                    UnmappedProviderField(
                        unmapped_field_id=f"unmapped-financial-field:{unmapped_digest}",
                        provider_id=row.provider_id,
                        statement_type=row.statement_type,
                        source_field=row.provider_field,
                        mapping_version_id=batch.work_unit.mapping_version_id,
                        discovered_at=batch.retrieved_at,
                        raw_object_id=row.raw_object_id,
                    )
                )
                unmapped_ids.append(row.row_id)
                continue
            mapping = mappings[0]
            if not mapping.allows(MappingUseScope(data_mode.value)):
                raise PermissionError(
                    "provider financial mapping is not allowed for current_research"
                )
            if mapping.method is MappingMethod.FORMULA:
                raise ValueError("formula financial mappings require an explicit formula evaluator")
            metric = self._repository.get_metric(mapping.metric_code)
            if metric is None:
                raise ValueError(f"canonical metric does not exist: {mapping.metric_code}")
            if metric.statement_type is not row.statement_type:
                raise ValueError("mapped metric statement does not match provider row")
            currency_units = {MetricUnit.CURRENCY, MetricUnit.CURRENCY_PER_SHARE}
            if metric.unit in currency_units and row.currency is None:
                raise ValueError("currency-valued mapped financial row requires currency")
            if metric.unit not in currency_units and row.currency is not None:
                raise ValueError("non-currency mapped financial row must not carry currency")
            mapped_digest = hashlib.sha256(
                f"{row.row_id}|{mapping.mapping_id}|{mapping.metric_code}".encode()
            ).hexdigest()[:24]
            mapped_rows.append(
                MappedFinancialRow(
                    mapped_row_id=f"mapped-financial-row:{mapped_digest}",
                    source_row=row,
                    mapping_id=mapping.mapping_id,
                    mapping_version_id=mapping.mapping_version_id,
                    metric_code=mapping.metric_code,
                    value=row.scaled_numeric_value,
                    unit=metric.unit,
                    currency=row.currency,
                    trust_state=batch.trust_state,
                )
            )
        warnings: tuple[str, ...] = ()
        if unmapped_ids:
            warnings = (f"unmapped_provider_field_count={len(unmapped_ids)}",)
        return FinancialMappingResult(
            provider_batch=batch,
            mapped_rows=tuple(mapped_rows),
            unmapped_row_ids=tuple(unmapped_ids),
            warnings=warnings,
        )


@dataclass(frozen=True)
class FinancialBackfillPreview:
    plan: FinancialBackfillPlan
    qualification: BackfillQualification
    work_units: tuple[FinancialBackfillWorkUnit, ...]


class FinancialBackfillPlanner:
    """Build deterministic work units without provider or storage I/O."""

    def preview(
        self,
        plan: FinancialBackfillPlan,
        profile: FinancialSourceProfile,
    ) -> FinancialBackfillPreview:
        units = self._work_units(plan)
        blockers: set[str] = set()
        warnings: set[str] = {
            "normalized_current financial rows are not PIT and cannot feed strict_historical",
            *profile.warnings,
        }
        if profile.provider_id != plan.provider_id:
            blockers.add("provider_id does not match the immutable financial backfill plan")
        if profile.profile_version != plan.provider_profile_version:
            blockers.add(
                "provider profile version does not match the immutable financial backfill plan"
            )
        if not plan.bulk_persistence_acknowledged:
            blockers.add("bulk persistence must be explicitly acknowledged")
        if plan.symbol_bucket_size > profile.max_rows_per_request:
            blockers.add("symbol bucket exceeds the provider profile row limit")

        markets = {
            "XSHG" if symbol.startswith("SH.") else "XSHE" for symbol in plan.symbols
        }
        for selection in plan.statements:
            for market in markets:
                if not profile.supports(
                    market=market,
                    statement_type=selection.statement_type,
                ):
                    blockers.add(
                        f"provider profile does not cover market={market}, "
                        f"statement={selection.statement_type.value}"
                    )
        try:
            profile.require_access(
                data_mode=plan.data_mode,
                bulk_persistence=True,
                allow_read_through_cache=plan.allow_read_through_cache,
            )
        except FinancialSourcePermissionError as error:
            blockers.add(str(error))

        qualification = BackfillQualification(
            provider_id=plan.provider_id,
            permitted=not blockers,
            evaluated_at=plan.created_at,
            blockers=tuple(sorted(blockers)),
            warnings=tuple(sorted(warnings)),
        )
        return FinancialBackfillPreview(
            plan=plan,
            qualification=qualification,
            work_units=units,
        )

    @staticmethod
    def _work_units(plan: FinancialBackfillPlan) -> tuple[FinancialBackfillWorkUnit, ...]:
        buckets = tuple(
            plan.symbols[index : index + plan.symbol_bucket_size]
            for index in range(0, len(plan.symbols), plan.symbol_bucket_size)
        )
        units: list[FinancialBackfillWorkUnit] = []
        for selection in plan.statements:
            for report_period_end in plan.report_period_ends:
                for offset, symbols in enumerate(buckets, start=1):
                    bucket_id = f"bucket-{offset:04d}"
                    checkpoint_key = (
                        f"{BackfillDataDomain.FINANCIAL_STATEMENT.value}:"
                        f"{plan.provider_id}:{plan.cohort.value}:"
                        f"{selection.provider_table}:{report_period_end.isoformat()}:"
                        f"{bucket_id}"
                    )
                    units.append(
                        FinancialBackfillWorkUnit(
                            plan_id=plan.plan_id,
                            checkpoint_key=checkpoint_key,
                            provider_id=plan.provider_id,
                            provider_profile_version=plan.provider_profile_version,
                            benchmark_id=plan.benchmark_id,
                            universe_version_id=plan.universe_version_id,
                            mapping_version_id=plan.mapping_version_id,
                            statement_type=selection.statement_type,
                            provider_table=selection.provider_table,
                            report_period_end=report_period_end,
                            symbol_bucket_id=bucket_id,
                            symbols=symbols,
                        )
                    )
        return tuple(sorted(units, key=lambda item: item.checkpoint_key))

    @staticmethod
    def pending_checkpoint(
        *,
        job_id: str,
        unit: FinancialBackfillWorkUnit,
        at: datetime,
    ) -> BackfillCheckpoint:
        return BackfillCheckpoint.pending(
            job_id=job_id,
            checkpoint_key=unit.checkpoint_key,
            scope_id=unit.benchmark_id,
            domain=BackfillDataDomain.FINANCIAL_STATEMENT,
            market=None,
            start_date=unit.report_period_end,
            end_date=unit.report_period_end,
            at=at,
        )

    @staticmethod
    def complete_checkpoint(
        checkpoint: BackfillCheckpoint,
        *,
        result: FinancialBackfillBatchResult,
        at: datetime,
    ) -> BackfillCheckpoint:
        if checkpoint.checkpoint_key != result.work_unit.checkpoint_key:
            raise ValueError("checkpoint does not match the financial work unit")
        if checkpoint.domain is not BackfillDataDomain.FINANCIAL_STATEMENT:
            raise ValueError("checkpoint is not a financial_statement checkpoint")
        if checkpoint.status is not BackfillCheckpointStatus.RUNNING:
            raise ValueError("financial checkpoint must be running before completion")
        metadata = ProviderRetrievalMetadata(
            provider_id=result.work_unit.provider_id,
            retrieved_at=result.retrieved_at,
            cutoff_date=result.provider_cutoff_date,
            adjustment_mode="not_applicable",
            units=(),
            warnings=result.warnings,
        )
        return checkpoint.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=at,
            processed_rows=result.processed_provider_rows,
            rejected_rows=result.rejected_rows,
            content_hash=result.content_hash,
            retrieval_metadata=metadata,
        )

    @staticmethod
    def build_reports(
        *,
        job_id: str,
        dataset_version_id: str,
        result: FinancialBackfillBatchResult,
        created_at: datetime,
    ) -> tuple[DatasetQualityReport, DatasetCoverageReport]:
        digest = hashlib.sha256(
            result.work_unit.checkpoint_key.encode("utf-8")
        ).hexdigest()[:20]
        issue_total = sum(count for _code, count in result.issue_counts)
        quality = DatasetQualityReport(
            report_id=f"quality:{job_id}:{digest}",
            dataset_version_id=dataset_version_id,
            job_id=job_id,
            status=result.quality_status,
            created_at=created_at,
            checks_passed=(
                1 if result.quality_status is DatasetQualityStatus.PASSED else 0
            ),
            checks_failed=issue_total,
            issue_counts=result.issue_counts,
            warnings=result.warnings,
        )
        expected = len(result.work_unit.symbols)
        observed = len(result.accepted_symbols)
        missing = expected - observed
        coverage_warnings = result.warnings
        if missing:
            coverage_warnings = (*coverage_warnings, f"missing_security_count={missing}")
        coverage = DatasetCoverageReport(
            report_id=f"coverage:{job_id}:{digest}",
            dataset_version_id=dataset_version_id,
            job_id=job_id,
            scope_id=result.work_unit.benchmark_id,
            domain=BackfillDataDomain.FINANCIAL_STATEMENT,
            start_date=result.work_unit.report_period_end,
            end_date=result.work_unit.report_period_end,
            expected_rows=expected,
            observed_rows=observed,
            coverage_ratio=observed / expected,
            created_at=created_at,
            warnings=coverage_warnings,
        )
        return quality, coverage


class FinancialBackfillRunner:
    """Execute one work unit with durable running/terminal checkpoint boundaries."""

    def __init__(
        self,
        *,
        planner: FinancialBackfillPlanner,
        mapper: FinancialBackfillMapper,
        unit_of_work: FinancialBackfillUnitOfWork,
        clock: Callable[[], datetime],
    ) -> None:
        self._planner = planner
        self._mapper = mapper
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run_unit(
        self,
        *,
        plan: FinancialBackfillPlan,
        profile: FinancialSourceProfile,
        job_id: str,
        work_unit: FinancialBackfillWorkUnit,
        source: FinancialBackfillSource,
    ) -> FinancialBackfillRunOutcome:
        preview = self._planner.preview(plan, profile)
        if not preview.qualification.permitted:
            raise FinancialBackfillBlockedError("; ".join(preview.qualification.blockers))
        matching_units = tuple(unit for unit in preview.work_units if unit == work_unit)
        if len(matching_units) != 1:
            raise ValueError("financial work unit is not part of the immutable plan")
        if source.provider_id != plan.provider_id:
            raise ValueError("financial source provider does not match immutable plan")

        checkpoint = self._unit_of_work.get_checkpoint(job_id, work_unit.checkpoint_key)
        if checkpoint is not None and checkpoint.status is BackfillCheckpointStatus.SUCCEEDED:
            persisted = self._unit_of_work.get_persist_result(
                job_id,
                work_unit.checkpoint_key,
            )
            if persisted is None:
                raise RuntimeError(
                    "succeeded financial checkpoint is missing its persist result"
                )
            return FinancialBackfillRunOutcome(
                checkpoint=checkpoint,
                dataset_version_id=persisted.dataset_version_id,
                observation_ids=persisted.observation_ids,
                skipped=True,
            )
        if checkpoint is None:
            checkpoint = self._planner.pending_checkpoint(
                job_id=job_id,
                unit=work_unit,
                at=self._clock(),
            )
            checkpoint = self._unit_of_work.save_checkpoint(checkpoint)
            self._unit_of_work.commit()
        if checkpoint.status in {
            BackfillCheckpointStatus.PENDING,
            BackfillCheckpointStatus.FAILED,
        }:
            checkpoint = checkpoint.transition(
                BackfillCheckpointStatus.RUNNING,
                at=self._clock(),
            )
            checkpoint = self._unit_of_work.save_checkpoint(checkpoint)
            self._unit_of_work.commit()

        try:
            batch = source.fetch(
                work_unit,
                allow_read_through_cache=plan.allow_read_through_cache,
            )
            if batch.work_unit != work_unit:
                raise ValueError("financial source batch does not match work unit")
            if batch.trust_state is not plan.output_trust_state:
                raise ValueError("financial source batch trust does not match immutable plan")
            mapping_result = self._mapper.map(batch, data_mode=plan.data_mode)
            if not mapping_result.mapped_rows:
                raise ValueError("financial work unit produced no mapped observations")
            persisted = self._unit_of_work.persist(mapping_result)
            if len(persisted.observation_ids) != len(mapping_result.mapped_rows):
                raise ValueError("financial sink did not persist every mapped observation")

            missing_security_count = len(work_unit.symbols) - len(batch.accepted_symbols)
            issue_counts = tuple(
                (code, count)
                for code, count in (
                    ("missing_provider_value", batch.missing_value_count),
                    ("unmapped_provider_field", len(mapping_result.unmapped_row_ids)),
                    ("missing_security", missing_security_count),
                )
                if count
            )
            warnings = tuple(
                dict.fromkeys(
                    (*batch.warnings, *mapping_result.warnings, *persisted.warnings)
                )
            )
            result = FinancialBackfillBatchResult(
                work_unit=work_unit,
                retrieved_at=batch.retrieved_at,
                provider_cutoff_date=batch.retrieved_at.date(),
                content_hash=batch.content_hash,
                processed_provider_rows=batch.provider_record_count,
                canonical_observations=len(mapping_result.mapped_rows),
                rejected_rows=max(
                    0,
                    batch.provider_record_count - len(batch.accepted_symbols),
                ),
                accepted_symbols=batch.accepted_symbols,
                quality_status=(
                    DatasetQualityStatus.PASSED
                    if not issue_counts
                    else DatasetQualityStatus.WARNED
                ),
                issue_counts=issue_counts,
                warnings=warnings,
            )
            succeeded = self._planner.complete_checkpoint(
                checkpoint,
                result=result,
                at=self._clock(),
            )
            quality, coverage = self._planner.build_reports(
                job_id=job_id,
                dataset_version_id=persisted.dataset_version_id,
                result=result,
                created_at=self._clock(),
            )
            for upstream_id, relation in (
                (batch.raw_object_id, "evidence_for"),
                (plan.mapping_version_id, "mapped_by"),
                (plan.universe_version_id, "scoped_by"),
            ):
                self._unit_of_work.register_lineage(
                    LineageEdge(
                        upstream_id=upstream_id,
                        downstream_id=persisted.dataset_version_id,
                        relation=relation,
                    )
                )
            for observation_id in persisted.observation_ids:
                self._unit_of_work.register_lineage(
                    LineageEdge(
                        upstream_id=persisted.dataset_version_id,
                        downstream_id=observation_id,
                        relation="contains",
                    )
                )
            self._unit_of_work.save_checkpoint(succeeded)
            self._unit_of_work.save_quality_report(quality)
            self._unit_of_work.save_coverage_report(coverage)
            self._unit_of_work.commit()
            return FinancialBackfillRunOutcome(
                checkpoint=succeeded,
                dataset_version_id=persisted.dataset_version_id,
                observation_ids=persisted.observation_ids,
                skipped=False,
            )
        except Exception as error:
            self._unit_of_work.rollback()
            if checkpoint.status is not BackfillCheckpointStatus.SUCCEEDED:
                failed = checkpoint.transition(
                    BackfillCheckpointStatus.FAILED,
                    at=self._clock(),
                    error=f"{type(error).__name__}: {error}",
                )
                self._unit_of_work.save_checkpoint(failed)
                self._unit_of_work.commit()
            raise
