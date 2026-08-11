"""Immutable cross-job coverage and quality audit for a financial cohort."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.domain.backfill import BackfillJobStatus
from a_share_platform.domain.governance import DatasetVersion, LineageEdge, VersionConflictError
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

_SCHEMA_VERSION = "normalized-current-financial-cohort-audit:v2"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class FinancialCohortAuditSnapshot:
    """Independent database totals across all component jobs."""

    job_ids: tuple[str, ...]
    completed_work_units: int
    receipt_observation_count: int
    persisted_observation_count: int
    zero_observation_work_units: int
    rejected_rows: int
    observed_symbols: tuple[str, ...]
    coverage_report_count: int
    full_coverage_reports: int
    partial_coverage_reports: int
    zero_coverage_reports: int
    quality_report_count: int
    passed_quality_reports: int
    warned_quality_reports: int
    failed_quality_reports: int
    quality_issue_counts: tuple[tuple[str, int], ...]
    completed_at: datetime

    def __post_init__(self) -> None:
        job_ids = tuple(self.job_ids)
        if not job_ids or len(job_ids) != len(set(job_ids)):
            raise ValueError("job_ids must be non-empty and unique")
        for job_id in job_ids:
            _text(job_id, "job_id")
        object.__setattr__(self, "job_ids", tuple(sorted(job_ids)))
        for field_name in (
            "completed_work_units",
            "receipt_observation_count",
            "persisted_observation_count",
            "zero_observation_work_units",
            "rejected_rows",
            "coverage_report_count",
            "full_coverage_reports",
            "partial_coverage_reports",
            "zero_coverage_reports",
            "quality_report_count",
            "passed_quality_reports",
            "warned_quality_reports",
            "failed_quality_reports",
        ):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if (
            self.full_coverage_reports
            + self.partial_coverage_reports
            + self.zero_coverage_reports
            != self.coverage_report_count
        ):
            raise ValueError("coverage ratio counts must equal coverage_report_count")
        if (
            self.passed_quality_reports
            + self.warned_quality_reports
            + self.failed_quality_reports
            != self.quality_report_count
        ):
            raise ValueError("quality status counts must equal quality_report_count")
        symbols = tuple(self.observed_symbols)
        if len(symbols) != len(set(symbols)):
            raise ValueError("observed_symbols must be unique")
        for symbol in symbols:
            _text(symbol, "observed_symbol")
        object.__setattr__(self, "observed_symbols", tuple(sorted(symbols)))
        issues = tuple(self.quality_issue_counts)
        issue_codes = tuple(code for code, _count in issues)
        if len(issue_codes) != len(set(issue_codes)):
            raise ValueError("quality issue codes must be unique")
        for code, count in issues:
            _text(code, "quality issue code")
            if type(count) is not int or count <= 0:
                raise ValueError("quality issue counts must be positive integers")
        object.__setattr__(self, "quality_issue_counts", tuple(sorted(issues)))
        _aware(self.completed_at, "completed_at")


@dataclass(frozen=True)
class FinancialCohortAuditEvidence:
    dataset: DatasetVersion
    metadata: dict[str, object]
    lineage: tuple[LineageEdge, ...]
    expected_work_units: int
    completed_work_units: int
    security_count: int
    observation_count: int


@dataclass(frozen=True)
class FinancialCohortAuditOutcome:
    evidence: FinancialCohortAuditEvidence
    writes_performed: bool


class FinancialCohortAuditRepository(Protocol):
    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None: ...

    def get_snapshot(self, job_ids: tuple[str, ...]) -> FinancialCohortAuditSnapshot: ...

    def get_dataset_metadata(self, dataset_version_id: str) -> dict[str, object] | None: ...

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: dict[str, object],
    ) -> DatasetVersion: ...

    def register_lineage(self, value: LineageEdge) -> LineageEdge: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class FinancialCohortAuditService:
    """Validate and freeze one cohort assembled from disjoint completed jobs."""

    def __init__(self, repository: FinancialCohortAuditRepository) -> None:
        self._repository = repository

    def evaluate(
        self,
        *,
        job_ids: tuple[str, ...],
        expected_security_count: int,
    ) -> FinancialCohortAuditEvidence:
        normalized_job_ids = tuple(sorted(job_ids))
        if len(normalized_job_ids) < 2 or len(normalized_job_ids) != len(
            set(normalized_job_ids)
        ):
            raise ValueError("cohort audit requires at least two unique job_ids")
        if type(expected_security_count) is not int or expected_security_count <= 0:
            raise ValueError("expected_security_count must be a positive integer")
        jobs: list[FinancialBackfillJobRecord] = []
        for job_id in normalized_job_ids:
            _text(job_id, "job_id")
            value = self._repository.get_job(job_id)
            if value is None:
                raise LookupError(f"financial backfill job does not exist: {job_id}")
            if value.status is not BackfillJobStatus.SUCCEEDED or value.dataset_version_id is None:
                raise ValueError("cohort audit requires succeeded component jobs")
            jobs.append(value)
        ordered_jobs = tuple(sorted(jobs, key=lambda item: item.job_id))
        self._require_compatible(ordered_jobs)

        symbol_owner: dict[str, str] = {}
        for job in ordered_jobs:
            for symbol in job.plan.symbols:
                previous = symbol_owner.setdefault(symbol, job.job_id)
                if previous != job.job_id:
                    raise ValueError(
                        f"component financial job symbols overlap: {symbol}/{previous}/{job.job_id}"
                    )
        expected_symbols = tuple(sorted(symbol_owner))
        if len(expected_symbols) != expected_security_count:
            raise ValueError(
                f"combined security count={len(expected_symbols)} does not match "
                f"expected_security_count={expected_security_count}"
            )

        expected_work_units = sum(self._expected_work_units(job) for job in ordered_jobs)
        snapshot = self._repository.get_snapshot(normalized_job_ids)
        if snapshot.job_ids != normalized_job_ids:
            raise ValueError("cohort audit snapshot does not match component job_ids")
        if snapshot.completed_work_units != expected_work_units:
            raise ValueError(
                f"completed_work_units={snapshot.completed_work_units} does not match "
                f"expected_work_units={expected_work_units}"
            )
        if snapshot.receipt_observation_count != snapshot.persisted_observation_count:
            raise ValueError("receipt observation count does not match persisted observation count")
        if snapshot.observed_symbols != expected_symbols:
            missing = tuple(sorted(set(expected_symbols) - set(snapshot.observed_symbols)))
            extra = tuple(sorted(set(snapshot.observed_symbols) - set(expected_symbols)))
            raise ValueError(f"cohort observed symbols mismatch; missing={missing}; extra={extra}")
        if snapshot.rejected_rows:
            raise ValueError("cohort audit cannot pass with rejected financial rows")
        if snapshot.coverage_report_count != expected_work_units:
            raise ValueError("coverage report count does not match expected work units")
        if snapshot.quality_report_count != expected_work_units:
            raise ValueError("quality report count does not match expected work units")
        if snapshot.failed_quality_reports:
            raise ValueError("cohort audit cannot pass with failed quality reports")

        first = ordered_jobs[0].plan
        component_dataset_ids = tuple(
            sorted(str(job.dataset_version_id) for job in ordered_jobs)
        )
        components = [
            {
                "aggregate_dataset_version_id": job.dataset_version_id,
                "expected_work_units": self._expected_work_units(job),
                "job_id": job.job_id,
                "plan_id": job.plan.plan_id,
                "security_count": len(job.plan.symbols),
            }
            for job in ordered_jobs
        ]
        quality_status = "warned" if snapshot.warned_quality_reports else "passed"
        manifest: dict[str, object] = {
            "adjustment_mode": "not_applicable",
            "cohort": first.cohort.value,
            "component_dataset_version_ids": list(component_dataset_ids),
            "components": components,
            "coverage": {
                "completed_work_units": snapshot.completed_work_units,
                "expected_security_count": expected_security_count,
                "expected_work_units": expected_work_units,
                "full_reports": snapshot.full_coverage_reports,
                "observation_count": snapshot.persisted_observation_count,
                "observed_security_count": len(snapshot.observed_symbols),
                "partial_reports": snapshot.partial_coverage_reports,
                "ratio": snapshot.completed_work_units / expected_work_units,
                "zero_reports": snapshot.zero_coverage_reports,
            },
            "data_mode": DataMode.CURRENT_RESEARCH.value,
            "kind": "financial_cohort_audit",
            "mapping_version_id": first.mapping_version_id,
            "pit_verified": False,
            "provider_id": first.provider_id,
            "provider_profile_version": first.provider_profile_version,
            "quality": {
                "empty_work_units": snapshot.zero_observation_work_units,
                "failed_reports": snapshot.failed_quality_reports,
                "issue_counts": dict(snapshot.quality_issue_counts),
                "missing_values_zero_filled": False,
                "passed_reports": snapshot.passed_quality_reports,
                "rejected_rows": snapshot.rejected_rows,
                "status": quality_status,
                "warned_reports": snapshot.warned_quality_reports,
            },
            "report_period_end": max(first.report_period_ends).isoformat(),
            "report_period_start": min(first.report_period_ends).isoformat(),
            "schema_version": _SCHEMA_VERSION,
            "statement_types": [item.statement_type.value for item in first.statements],
            "trust_state": DataTrustState.NORMALIZED_CURRENT.value,
            "universe_version_id": first.universe_version_id,
            "warnings": [
                "normalized_current cohort audit is not PIT and cannot feed strict_historical",
                "empty provider periods are explicit and missing values were not zero-filled",
                "private local research only; redistribution and production decisions prohibited",
            ],
        }
        encoded = json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        created_at = max(snapshot.completed_at, *(job.updated_at for job in ordered_jobs))
        dataset = DatasetVersion(
            dataset_version_id=(
                f"dataset:financial-cohort-audit:{first.cohort.value}:{digest[:24]}:v2"
            ),
            content_hash=f"sha256:{digest}",
            created_at=created_at,
            schema_version=_SCHEMA_VERSION,
        )
        lineage = tuple(
            [
                LineageEdge(value, dataset.dataset_version_id, "aggregated_into")
                for value in component_dataset_ids
            ]
            + [
                LineageEdge(
                    first.mapping_version_id,
                    dataset.dataset_version_id,
                    "mapped_by",
                ),
                LineageEdge(
                    first.universe_version_id,
                    dataset.dataset_version_id,
                    "scoped_by",
                ),
            ]
        )
        return FinancialCohortAuditEvidence(
            dataset=dataset,
            metadata={"manifest": manifest},
            lineage=lineage,
            expected_work_units=expected_work_units,
            completed_work_units=snapshot.completed_work_units,
            security_count=len(snapshot.observed_symbols),
            observation_count=snapshot.persisted_observation_count,
        )

    def ensure(
        self,
        *,
        job_ids: tuple[str, ...],
        expected_security_count: int,
    ) -> FinancialCohortAuditOutcome:
        evidence = self.evaluate(
            job_ids=job_ids,
            expected_security_count=expected_security_count,
        )
        existing = self._repository.get_dataset_metadata(evidence.dataset.dataset_version_id)
        if existing is not None and existing != evidence.metadata:
            raise VersionConflictError(
                f"immutable financial cohort audit conflict: {evidence.dataset.dataset_version_id}"
            )
        try:
            if existing is None:
                stored = self._repository.register_dataset(
                    evidence.dataset,
                    metadata=evidence.metadata,
                )
                if stored != evidence.dataset:
                    raise VersionConflictError("financial cohort audit dataset was not observable")
            for edge in evidence.lineage:
                self._repository.register_lineage(edge)
            self._repository.commit()
        except Exception:
            self._repository.rollback()
            raise
        return FinancialCohortAuditOutcome(
            evidence=evidence,
            writes_performed=existing is None,
        )

    @staticmethod
    def _expected_work_units(job: FinancialBackfillJobRecord) -> int:
        plan = job.plan
        bucket_count = (len(plan.symbols) + plan.symbol_bucket_size - 1) // plan.symbol_bucket_size
        return len(plan.statements) * len(plan.report_period_ends) * bucket_count

    @staticmethod
    def _require_compatible(jobs: tuple[FinancialBackfillJobRecord, ...]) -> None:
        first = jobs[0].plan
        if first.data_mode is not DataMode.CURRENT_RESEARCH:
            raise PermissionError("financial cohort audit must remain current_research")
        if first.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise PermissionError("financial cohort audit must remain normalized_current")
        dimensions = (
            "cohort",
            "provider_id",
            "provider_profile_version",
            "universe_version_id",
            "mapping_version_id",
            "statements",
            "report_period_ends",
            "data_mode",
            "output_trust_state",
        )
        for job in jobs[1:]:
            mismatches = tuple(
                field_name
                for field_name in dimensions
                if getattr(job.plan, field_name) != getattr(first, field_name)
            )
            if mismatches:
                raise ValueError(f"component financial jobs are incompatible: {mismatches}")


__all__ = [
    "FinancialCohortAuditEvidence",
    "FinancialCohortAuditOutcome",
    "FinancialCohortAuditRepository",
    "FinancialCohortAuditService",
    "FinancialCohortAuditSnapshot",
]
