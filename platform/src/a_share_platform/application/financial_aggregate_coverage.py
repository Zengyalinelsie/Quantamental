"""Aggregate coverage evidence for a completed P3.5 financial backfill."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.domain.backfill import (
    BackfillDataDomain,
    BackfillJobStatus,
    DatasetCoverageReport,
)
from a_share_platform.domain.financial_backfill import FinancialBackfillCohort
from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class FinancialAggregateCoverageSnapshot:
    """Independent database counts used to detect incomplete aggregate evidence."""

    job_id: str
    completed_work_units: int
    receipt_observation_count: int
    persisted_observation_count: int
    observed_symbols: tuple[str, ...]
    completed_at: datetime

    def __post_init__(self) -> None:
        _text(self.job_id, "job_id")
        for value, field_name in (
            (self.completed_work_units, "completed_work_units"),
            (self.receipt_observation_count, "receipt_observation_count"),
            (self.persisted_observation_count, "persisted_observation_count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        symbols = tuple(self.observed_symbols)
        if len(symbols) != len(set(symbols)):
            raise ValueError("observed_symbols must be unique")
        for symbol in symbols:
            _text(symbol, "observed_symbol")
        object.__setattr__(self, "observed_symbols", tuple(sorted(symbols)))
        _aware(self.completed_at, "completed_at")


@dataclass(frozen=True)
class FinancialAggregateCoverageEvidence:
    report: DatasetCoverageReport
    expected_work_units: int
    completed_work_units: int
    expected_security_count: int
    observed_security_count: int
    canonical_observation_count: int


@dataclass(frozen=True)
class FinancialAggregateCoverageOutcome:
    evidence: FinancialAggregateCoverageEvidence
    writes_performed: bool


class FinancialAggregateCoverageRepository(Protocol):
    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None: ...

    def get_snapshot(self, job_id: str) -> FinancialAggregateCoverageSnapshot: ...

    def get_coverage_report(self, report_id: str) -> DatasetCoverageReport | None: ...

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class FinancialAggregateCoverageService:
    """Build and persist one immutable CSI300 predecessor coverage report."""

    def __init__(self, repository: FinancialAggregateCoverageRepository) -> None:
        self._repository = repository

    def evaluate(self, job_id: str) -> FinancialAggregateCoverageEvidence:
        _text(job_id, "job_id")
        job = self._repository.get_job(job_id)
        if job is None:
            raise LookupError(f"financial backfill job does not exist: {job_id}")
        if job.status is not BackfillJobStatus.SUCCEEDED or job.dataset_version_id is None:
            raise ValueError("aggregate coverage requires a succeeded financial job")
        plan = job.plan
        if plan.cohort is not FinancialBackfillCohort.CSI_300:
            raise ValueError("CSI500 predecessor coverage must come from a CSI300 job")
        if plan.data_mode is not DataMode.CURRENT_RESEARCH:
            raise PermissionError("financial aggregate coverage must remain current_research")
        if plan.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise PermissionError("financial aggregate coverage must remain normalized_current")

        snapshot = self._repository.get_snapshot(job_id)
        if snapshot.job_id != job_id:
            raise ValueError("aggregate coverage snapshot does not match the requested job")
        bucket_count = (len(plan.symbols) + plan.symbol_bucket_size - 1) // plan.symbol_bucket_size
        expected_work_units = len(plan.statements) * len(plan.report_period_ends) * bucket_count
        if snapshot.completed_work_units != expected_work_units:
            raise ValueError(
                f"completed_work_units={snapshot.completed_work_units} does not match "
                f"expected_work_units={expected_work_units}"
            )
        if snapshot.receipt_observation_count <= 0:
            raise ValueError("aggregate coverage requires persisted financial observations")
        if snapshot.receipt_observation_count != snapshot.persisted_observation_count:
            raise ValueError("receipt observation count does not match persisted observation count")
        expected_symbols = tuple(sorted(plan.symbols))
        if snapshot.observed_symbols != expected_symbols:
            missing = tuple(sorted(set(expected_symbols) - set(snapshot.observed_symbols)))
            extra = tuple(sorted(set(snapshot.observed_symbols) - set(expected_symbols)))
            raise ValueError(
                "observed financial symbols do not match immutable plan; "
                f"missing={missing}; extra={extra}"
            )

        report = DatasetCoverageReport(
            report_id=f"coverage:{job_id}:aggregate:v1",
            dataset_version_id=job.dataset_version_id,
            job_id=job_id,
            scope_id=plan.benchmark_id,
            domain=BackfillDataDomain.FINANCIAL_STATEMENT,
            start_date=min(plan.report_period_ends),
            end_date=max(plan.report_period_ends),
            expected_rows=expected_work_units,
            observed_rows=snapshot.completed_work_units,
            coverage_ratio=snapshot.completed_work_units / expected_work_units,
            created_at=max(job.updated_at, snapshot.completed_at),
            warnings=(
                "coverage_basis=completed_financial_work_units",
                f"expected_work_units={expected_work_units}",
                f"completed_work_units={snapshot.completed_work_units}",
                f"expected_security_count={len(expected_symbols)}",
                f"observed_security_count={len(snapshot.observed_symbols)}",
                (f"canonical_observation_count={snapshot.persisted_observation_count}"),
                f"data_mode={DataMode.CURRENT_RESEARCH.value}",
                f"trust_state={DataTrustState.NORMALIZED_CURRENT.value}",
                "pit_verified=false",
            ),
        )
        return FinancialAggregateCoverageEvidence(
            report=report,
            expected_work_units=expected_work_units,
            completed_work_units=snapshot.completed_work_units,
            expected_security_count=len(expected_symbols),
            observed_security_count=len(snapshot.observed_symbols),
            canonical_observation_count=snapshot.persisted_observation_count,
        )

    def ensure(self, job_id: str) -> FinancialAggregateCoverageOutcome:
        evidence = self.evaluate(job_id)
        expected = evidence.report
        existing = self._repository.get_coverage_report(expected.report_id)
        if existing is not None:
            if existing != expected:
                raise VersionConflictError(
                    f"immutable financial aggregate coverage conflict: {expected.report_id}"
                )
            return FinancialAggregateCoverageOutcome(
                evidence=evidence,
                writes_performed=False,
            )
        try:
            self._repository.save_coverage_report(expected)
            stored = self._repository.get_coverage_report(expected.report_id)
            if stored != expected:
                raise VersionConflictError(
                    f"financial aggregate coverage write was not observable: {expected.report_id}"
                )
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return FinancialAggregateCoverageOutcome(
            evidence=evidence,
            writes_performed=True,
        )


__all__ = [
    "FinancialAggregateCoverageEvidence",
    "FinancialAggregateCoverageOutcome",
    "FinancialAggregateCoverageRepository",
    "FinancialAggregateCoverageService",
    "FinancialAggregateCoverageSnapshot",
]
