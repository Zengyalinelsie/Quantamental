"""Planning, qualification, and resumable execution of A-share backfills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from a_share_platform.domain.backfill import (
    A_SHARE_SECURITY_MASTER_SCOPE,
    CSI_300_SCOPE,
    CSI_500_SCOPE,
    BackfillBatch,
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    BackfillDataDomain,
    BackfillJob,
    BackfillJobStatus,
    BackfillPlan,
    BackfillQualification,
    BackfillScopeKind,
    BackfillWorkUnit,
    DatasetCoverageReport,
    DatasetQualityReport,
    DatasetQualityStatus,
)
from a_share_platform.domain.governance import DatasetVersion
from a_share_platform.domain.market_data import PriceAdjustment
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import DataField, ProviderRegistry, ProviderUse
from a_share_platform.ports.backfill import (
    BackfillRepository,
    BackfillSink,
    BackfillSource,
)
from a_share_platform.ports.governance import GovernanceRepository

_MARKETS = ("XSHG", "XSHE", "XBSE")
_INDEX_MARKETS = ("XSHG", "XSHE")
_DOMAIN_FIELDS: dict[BackfillDataDomain, tuple[DataField, ...]] = {
    BackfillDataDomain.SECURITY_MASTER: (
        DataField.SECURITY_IDENTITY,
        DataField.IDENTIFIER_HISTORY,
        DataField.LISTING_STATUS,
        DataField.INDUSTRY_MEMBERSHIP,
    ),
    BackfillDataDomain.UNIVERSE: (DataField.BENCHMARK_MEMBERSHIP,),
    BackfillDataDomain.RAW_DAILY_BAR: (DataField.RAW_DAILY_BAR,),
    BackfillDataDomain.SHARE_CAPITAL: (DataField.SHARE_CAPITAL,),
    BackfillDataDomain.CORPORATE_ACTION: (DataField.CORPORATE_ACTION,),
    BackfillDataDomain.TRADING_CALENDAR: (DataField.TRADING_CALENDAR,),
}
_TRUST_ORDER = {
    DataTrustState.RAW: 0,
    DataTrustState.NORMALIZED_CURRENT: 1,
    DataTrustState.PIT_VERIFIED: 2,
}


@dataclass(frozen=True)
class BackfillPreview:
    plan: BackfillPlan
    qualification: BackfillQualification
    work_units: tuple[BackfillWorkUnit, ...]


def build_csi_backfill_plan(
    *,
    plan_id: str,
    provider_id: str,
    end_date: date,
    created_at: datetime,
    start_date: date = date(2018, 1, 1),
) -> BackfillPlan:
    """Build the canonical user-requested full-master + CSI 300/500 plan."""

    return BackfillPlan(
        plan_id=plan_id,
        provider_id=provider_id,
        scopes=(A_SHARE_SECURITY_MASTER_SCOPE, CSI_300_SCOPE, CSI_500_SCOPE),
        domains=tuple(BackfillDataDomain),
        start_date=start_date,
        end_date=end_date,
        created_at=created_at,
        output_trust_state=DataTrustState.NORMALIZED_CURRENT,
        price_adjustment=PriceAdjustment.UNADJUSTED,
    )


class BackfillPlanner:
    """Create deterministic annual work units suitable for checkpoints."""

    def work_units(self, plan: BackfillPlan) -> tuple[BackfillWorkUnit, ...]:
        units: list[BackfillWorkUnit] = []
        master_scopes = tuple(
            scope for scope in plan.scopes if scope.kind is BackfillScopeKind.SECURITY_MASTER
        )
        index_scopes = tuple(
            scope for scope in plan.scopes if scope.kind is BackfillScopeKind.INDEX_UNIVERSE
        )
        for domain in plan.domains:
            scope_markets: tuple[tuple[str, str | None], ...]
            if domain is BackfillDataDomain.SECURITY_MASTER or domain is BackfillDataDomain.TRADING_CALENDAR:
                scope_markets = tuple(
                    (scope.scope_id, market) for scope in master_scopes for market in _MARKETS
                )
            elif domain is BackfillDataDomain.UNIVERSE:
                scope_markets = tuple((scope.scope_id, None) for scope in index_scopes)
            else:
                scope_markets = tuple(
                    (scope.scope_id, market)
                    for scope in index_scopes
                    for market in _INDEX_MARKETS
                )
            for scope_id, market in scope_markets:
                for start_date, end_date in self._annual_ranges(
                    plan.start_date,
                    plan.end_date,
                ):
                    market_key = market or "ALL"
                    checkpoint_key = ":".join(
                        (
                            domain.value,
                            scope_id.replace(":", "-"),
                            market_key,
                            start_date.isoformat(),
                            end_date.isoformat(),
                        )
                    )
                    units.append(
                        BackfillWorkUnit(
                            plan_id=plan.plan_id,
                            checkpoint_key=checkpoint_key,
                            scope_id=scope_id,
                            domain=domain,
                            market=market,
                            start_date=start_date,
                            end_date=end_date,
                        )
                    )
        return tuple(sorted(units, key=lambda item: item.checkpoint_key))

    @staticmethod
    def _annual_ranges(start_date: date, end_date: date) -> tuple[tuple[date, date], ...]:
        ranges: list[tuple[date, date]] = []
        year = start_date.year
        while year <= end_date.year:
            lower = max(start_date, date(year, 1, 1))
            upper = min(end_date, date(year, 12, 31))
            ranges.append((lower, upper))
            year += 1
        return tuple(ranges)


class BackfillService:
    """Fail closed on data use, then run idempotent checkpointed ingestion."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        repository: BackfillRepository,
        clock: Callable[[], datetime],
        planner: BackfillPlanner | None = None,
        governance_repository: GovernanceRepository | None = None,
    ) -> None:
        self._registry = registry
        self._repository = repository
        self._clock = clock
        self._planner = planner or BackfillPlanner()
        self._governance = governance_repository

    def preview(self, plan: BackfillPlan) -> BackfillPreview:
        return BackfillPreview(
            plan=plan,
            qualification=self._qualify(plan),
            work_units=self._planner.work_units(plan),
        )

    def start(
        self,
        plan: BackfillPlan,
        *,
        source: BackfillSource | None,
        sink: BackfillSink | None,
    ) -> BackfillJob:
        preview = self.preview(plan)
        existing = self._repository.get_job(f"job:{plan.plan_id}")
        if existing is not None:
            if existing.plan != plan:
                raise ValueError(f"existing backfill job has a different plan: {existing.job_id}")
            if existing.status in {BackfillJobStatus.BLOCKED, BackfillJobStatus.SUCCEEDED}:
                return existing

        if not preview.qualification.permitted:
            job = BackfillJob.blocked(plan, preview.qualification)
            return self._repository.save_job(job) if existing is None else existing

        if existing is None:
            job = self._repository.save_job(BackfillJob.planned(plan, preview.qualification))
        else:
            job = existing
        if job.status in {BackfillJobStatus.PLANNED, BackfillJobStatus.FAILED}:
            job = self._repository.append_job_state(
                job.transition(BackfillJobStatus.RUNNING, at=self._clock())
            )
        if source is None or sink is None or self._governance is None:
            failure = ("approved source, sink, and governance repository are required",)
            failed = job.transition(BackfillJobStatus.FAILED, at=self._clock(), failure_reason=failure)
            return self._repository.append_job_state(failed)
        if source.provider_id != plan.provider_id:
            failure = ("source provider_id does not match the immutable backfill plan",)
            failed = job.transition(BackfillJobStatus.FAILED, at=self._clock(), failure_reason=failure)
            return self._repository.append_job_state(failed)

        return self._execute(job, preview.work_units, source, sink)

    def _execute(
        self,
        job: BackfillJob,
        units: tuple[BackfillWorkUnit, ...],
        source: BackfillSource,
        sink: BackfillSink,
    ) -> BackfillJob:
        pending_batches: list[tuple[BackfillCheckpoint, BackfillBatch]] = []
        content_by_key: dict[str, str] = {}
        current_checkpoint: BackfillCheckpoint | None = None
        try:
            for unit in units:
                checkpoint = self._repository.get_checkpoint(job.job_id, unit.checkpoint_key)
                if checkpoint is None:
                    checkpoint = self._repository.save_checkpoint(
                        BackfillCheckpoint.pending(
                            job_id=job.job_id,
                            checkpoint_key=unit.checkpoint_key,
                            scope_id=unit.scope_id,
                            domain=unit.domain,
                            market=unit.market,
                            start_date=unit.start_date,
                            end_date=unit.end_date,
                            at=self._clock(),
                        )
                    )
                if checkpoint.status is BackfillCheckpointStatus.SUCCEEDED:
                    if checkpoint.content_hash is None:  # defensive against repository corruption
                        raise ValueError("succeeded checkpoint is missing its content hash")
                    content_by_key[checkpoint.checkpoint_key] = checkpoint.content_hash
                    continue
                if checkpoint.status in {
                    BackfillCheckpointStatus.PENDING,
                    BackfillCheckpointStatus.FAILED,
                }:
                    checkpoint = self._repository.save_checkpoint(
                        checkpoint.transition(BackfillCheckpointStatus.RUNNING, at=self._clock())
                    )
                current_checkpoint = checkpoint
                batch = source.fetch(unit, job.plan)
                self._validate_batch(job.plan, unit, batch)
                pending_batches.append((checkpoint, batch))
                content_by_key[unit.checkpoint_key] = batch.content_hash

            dataset = self._register_dataset(job.plan, content_by_key)
            for checkpoint, batch in pending_batches:
                current_checkpoint = checkpoint
                sink.persist(batch, dataset_version_id=dataset.dataset_version_id)
                succeeded = checkpoint.transition(
                    BackfillCheckpointStatus.SUCCEEDED,
                    at=self._clock(),
                    processed_rows=batch.row_count,
                    rejected_rows=batch.rejected_rows,
                    content_hash=batch.content_hash,
                    retrieval_metadata=batch.metadata,
                )
                self._repository.save_checkpoint(succeeded)
                self._save_batch_reports(job, dataset, batch)
                current_checkpoint = None
            succeeded_job = job.transition(
                BackfillJobStatus.SUCCEEDED,
                at=self._clock(),
                dataset_version_id=dataset.dataset_version_id,
            )
            return self._repository.append_job_state(succeeded_job)
        except Exception as error:
            if current_checkpoint is not None and current_checkpoint.status is not BackfillCheckpointStatus.SUCCEEDED:
                failed_checkpoint = current_checkpoint.transition(
                    BackfillCheckpointStatus.FAILED,
                    at=self._clock(),
                    error=f"{type(error).__name__}: {error}",
                )
                self._repository.save_checkpoint(failed_checkpoint)
            failed_job = job.transition(
                BackfillJobStatus.FAILED,
                at=self._clock(),
                failure_reason=(f"{type(error).__name__}: {error}",),
            )
            self._repository.append_job_state(failed_job)
            raise

    def _qualify(self, plan: BackfillPlan) -> BackfillQualification:
        blockers: set[str] = set()
        warnings: set[str] = {
            "retrieval time and historical dates do not prove PIT availability",
        }
        for domain in plan.domains:
            markets = _MARKETS if domain in {
                BackfillDataDomain.SECURITY_MASTER,
                BackfillDataDomain.TRADING_CALENDAR,
            } else _INDEX_MARKETS
            for field in _DOMAIN_FIELDS[domain]:
                for market in markets:
                    try:
                        policy = self._registry.policy(plan.provider_id, field)
                    except KeyError:
                        blockers.add(
                            f"provider={plan.provider_id} has no capability for "
                            f"field={field.value}, market={market}"
                        )
                        continue
                    if not policy.allows(ProviderUse.RAW_BULK_PERSISTENCE, market):
                        blockers.add(
                            f"provider={plan.provider_id} is not qualified for "
                            f"use={ProviderUse.RAW_BULK_PERSISTENCE.value}, "
                            f"field={field.value}, market={market}, "
                            f"license_status={policy.license_status.value}"
                        )
                    if _TRUST_ORDER[plan.output_trust_state] > _TRUST_ORDER[policy.trust_ceiling]:
                        blockers.add(
                            f"provider={plan.provider_id} trust ceiling={policy.trust_ceiling.value} "
                            f"cannot emit {plan.output_trust_state.value} for field={field.value}"
                        )
                    if policy.warning:
                        warnings.add(f"{field.value}: {policy.warning}")
        return BackfillQualification(
            provider_id=plan.provider_id,
            permitted=not blockers,
            evaluated_at=self._clock(),
            blockers=tuple(sorted(blockers)),
            warnings=tuple(sorted(warnings)),
        )

    @staticmethod
    def _validate_batch(
        plan: BackfillPlan,
        unit: BackfillWorkUnit,
        batch: BackfillBatch,
    ) -> None:
        if batch.work_unit != unit:
            raise ValueError("provider batch does not match requested checkpoint")
        if batch.metadata.provider_id != plan.provider_id:
            raise ValueError("provider metadata does not match the immutable plan")
        if batch.metadata.adjustment_mode != PriceAdjustment.UNADJUSTED.value:
            raise ValueError("only raw unadjusted market data may enter this backfill")
        if batch.trust_state is not plan.output_trust_state:
            raise ValueError("provider batch trust state does not match the immutable plan")
        if batch.metadata.cutoff_date is not None and batch.metadata.cutoff_date > plan.end_date:
            raise ValueError("provider cutoff exceeds the immutable plan end_date")

    def _register_dataset(
        self,
        plan: BackfillPlan,
        content_by_key: dict[str, str],
    ) -> DatasetVersion:
        if self._governance is None:  # guarded by start; retained for type narrowing
            raise RuntimeError("governance repository is unavailable")
        manifest = json.dumps(
            {
                "plan_id": plan.plan_id,
                "provider_id": plan.provider_id,
                "start_date": plan.start_date.isoformat(),
                "end_date": plan.end_date.isoformat(),
                "trust_state": plan.output_trust_state.value,
                "adjustment": plan.price_adjustment.value,
                "batches": sorted(content_by_key.items()),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        dataset = DatasetVersion(
            dataset_version_id=f"dataset:backfill:{plan.plan_id}:v1",
            content_hash=f"sha256:{hashlib.sha256(manifest).hexdigest()}",
            created_at=plan.created_at,
            schema_version="p2-backfill-v1",
        )
        return self._governance.register_dataset(dataset)

    def _save_batch_reports(
        self,
        job: BackfillJob,
        dataset: DatasetVersion,
        batch: BackfillBatch,
    ) -> None:
        key_hash = hashlib.sha256(batch.work_unit.checkpoint_key.encode("utf-8")).hexdigest()[:20]
        issue_total = sum(count for _code, count in batch.issue_counts)
        quality = DatasetQualityReport(
            report_id=f"quality:{job.job_id}:{key_hash}",
            dataset_version_id=dataset.dataset_version_id,
            job_id=job.job_id,
            status=batch.quality_status,
            created_at=self._clock(),
            checks_passed=1 if batch.quality_status is DatasetQualityStatus.PASSED else 0,
            checks_failed=issue_total,
            issue_counts=batch.issue_counts,
            warnings=(*batch.metadata.warnings, *batch.warnings),
        )
        self._repository.save_quality_report(quality)
        ratio = None
        if batch.expected_rows not in {None, 0}:
            ratio = min(1.0, batch.row_count / batch.expected_rows)
        coverage = DatasetCoverageReport(
            report_id=f"coverage:{job.job_id}:{key_hash}",
            dataset_version_id=dataset.dataset_version_id,
            job_id=job.job_id,
            scope_id=batch.work_unit.scope_id,
            domain=batch.work_unit.domain,
            start_date=batch.work_unit.start_date,
            end_date=batch.work_unit.end_date,
            expected_rows=batch.expected_rows,
            observed_rows=batch.row_count,
            coverage_ratio=ratio,
            created_at=self._clock(),
            warnings=batch.warnings,
        )
        self._repository.save_coverage_report(coverage)
