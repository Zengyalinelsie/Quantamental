"""Provider-neutral orchestration of a complete checkpointed financial plan."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from a_share_platform.application.financial_backfill import (
    FinancialBackfillBlockedError,
    FinancialBackfillPlanner,
    FinancialBackfillPreview,
    FinancialBackfillRunOutcome,
)
from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.domain.backfill import BackfillJobStatus
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillPlan,
    FinancialBackfillWorkUnit,
)
from a_share_platform.domain.financial_sources import FinancialSourceProfile
from a_share_platform.ports.financial_backfill import FinancialBackfillSource


class FinancialUnitRunner(Protocol):
    def run_unit(
        self,
        *,
        plan: FinancialBackfillPlan,
        profile: FinancialSourceProfile,
        job_id: str,
        work_unit: FinancialBackfillWorkUnit,
        source: FinancialBackfillSource,
    ) -> FinancialBackfillRunOutcome: ...


class FinancialJobCoordinator(Protocol):
    def bootstrap(self, preview: FinancialBackfillPreview) -> FinancialBackfillJobRecord: ...

    def finalize(self, preview: FinancialBackfillPreview) -> FinancialBackfillJobRecord: ...

    def fail(
        self,
        preview: FinancialBackfillPreview,
        reason: str,
    ) -> FinancialBackfillJobRecord: ...


@dataclass(frozen=True)
class FinancialBackfillExecutionResult:
    job_id: str
    status: BackfillJobStatus
    writes_performed: bool
    completed_work_units: int
    skipped_work_units: int
    unit_dataset_version_ids: tuple[str, ...]
    aggregate_dataset_version_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.job_id, str) or not self.job_id.strip():
            raise ValueError("job_id must not be empty")
        status = BackfillJobStatus(self.status)
        object.__setattr__(self, "status", status)
        if status is not BackfillJobStatus.SUCCEEDED:
            raise ValueError("financial execution result must be succeeded")
        if type(self.writes_performed) is not bool:
            raise TypeError("writes_performed must be a boolean")
        for value, name in (
            (self.completed_work_units, "completed_work_units"),
            (self.skipped_work_units, "skipped_work_units"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.skipped_work_units > self.completed_work_units:
            raise ValueError("skipped_work_units cannot exceed completed_work_units")
        unit_ids = tuple(self.unit_dataset_version_ids)
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("unit dataset version identifiers must be unique")
        for dataset_id in (*unit_ids, self.aggregate_dataset_version_id):
            if not isinstance(dataset_id, str) or not dataset_id.strip():
                raise ValueError("dataset version identifiers must not be empty")
        object.__setattr__(self, "unit_dataset_version_ids", unit_ids)


class FinancialBackfillExecutionService:
    """Resume a plan, run pending units sequentially, then close the aggregate."""

    def __init__(
        self,
        *,
        planner: FinancialBackfillPlanner,
        job_coordinator: FinancialJobCoordinator,
        runner: FinancialUnitRunner,
    ) -> None:
        self._planner = planner
        self._job_coordinator = job_coordinator
        self._runner = runner

    def run(
        self,
        *,
        plan: FinancialBackfillPlan,
        profile: FinancialSourceProfile,
        source: FinancialBackfillSource,
    ) -> FinancialBackfillExecutionResult:
        preview = self._planner.preview(plan, profile)
        job = self._job_coordinator.bootstrap(preview)
        if job.status is BackfillJobStatus.BLOCKED:
            raise FinancialBackfillBlockedError("; ".join(job.failure_reasons))
        if job.status is BackfillJobStatus.SUCCEEDED:
            assert job.dataset_version_id is not None
            return FinancialBackfillExecutionResult(
                job_id=job.job_id,
                status=job.status,
                writes_performed=False,
                completed_work_units=len(preview.work_units),
                skipped_work_units=len(preview.work_units),
                unit_dataset_version_ids=(),
                aggregate_dataset_version_id=job.dataset_version_id,
            )
        if job.status is not BackfillJobStatus.RUNNING:
            raise RuntimeError("financial job did not enter running state")

        outcomes: list[FinancialBackfillRunOutcome] = []
        try:
            for work_unit in preview.work_units:
                outcomes.append(
                    self._runner.run_unit(
                        plan=plan,
                        profile=profile,
                        job_id=job.job_id,
                        work_unit=work_unit,
                        source=source,
                    )
                )
            finalized = self._job_coordinator.finalize(preview)
        except Exception as error:
            self._job_coordinator.fail(preview, f"{type(error).__name__}: {error}")
            raise

        if finalized.status is not BackfillJobStatus.SUCCEEDED:
            raise RuntimeError("financial aggregate finalization did not succeed")
        assert finalized.dataset_version_id is not None
        unit_dataset_ids = tuple(
            outcome.dataset_version_id
            for outcome in outcomes
            if outcome.dataset_version_id is not None
        )
        if len(unit_dataset_ids) != len(outcomes):
            raise RuntimeError("completed financial work unit is missing its dataset version")
        return FinancialBackfillExecutionResult(
            job_id=finalized.job_id,
            status=finalized.status,
            writes_performed=True,
            completed_work_units=len(outcomes),
            skipped_work_units=sum(outcome.skipped for outcome in outcomes),
            unit_dataset_version_ids=unit_dataset_ids,
            aggregate_dataset_version_id=finalized.dataset_version_id,
        )


__all__ = [
    "FinancialBackfillExecutionResult",
    "FinancialBackfillExecutionService",
    "FinancialJobCoordinator",
    "FinancialUnitRunner",
]
