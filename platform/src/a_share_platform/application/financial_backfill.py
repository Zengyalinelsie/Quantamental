"""Read-only planning and ledger projection for P3.5 financial scale-up."""

from __future__ import annotations

import hashlib
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
)
from a_share_platform.domain.financial_sources import (
    FinancialSourcePermissionError,
    FinancialSourceProfile,
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
