"""In-memory backfill ledger used for deterministic application tests."""

from __future__ import annotations

from typing import TypeVar

from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    BackfillJob,
    DatasetCoverageReport,
    DatasetQualityReport,
)
from a_share_platform.domain.governance import VersionConflictError

_Report = TypeVar("_Report", DatasetQualityReport, DatasetCoverageReport)


class InMemoryBackfillRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, BackfillJob] = {}
        self._job_history: dict[str, list[BackfillJob]] = {}
        self._checkpoints: dict[tuple[str, str], BackfillCheckpoint] = {}
        self._quality: dict[str, DatasetQualityReport] = {}
        self._coverage: dict[str, DatasetCoverageReport] = {}

    def save_job(self, value: BackfillJob) -> BackfillJob:
        existing = self._jobs.get(value.job_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(f"backfill job identifier conflict: {value.job_id}")
            return existing
        self._jobs[value.job_id] = value
        self._job_history[value.job_id] = [value]
        return value

    def append_job_state(self, value: BackfillJob) -> BackfillJob:
        if value.job_id not in self._jobs:
            raise KeyError(value.job_id)
        self._jobs[value.job_id] = value
        self._job_history[value.job_id].append(value)
        return value

    def get_job(self, job_id: str) -> BackfillJob | None:
        return self._jobs.get(job_id)

    def list_jobs(self) -> tuple[BackfillJob, ...]:
        return tuple(self._jobs[key] for key in sorted(self._jobs))

    def job_history(self, job_id: str) -> tuple[BackfillJob, ...]:
        return tuple(self._job_history.get(job_id, ()))

    def save_checkpoint(self, value: BackfillCheckpoint) -> BackfillCheckpoint:
        key = (value.job_id, value.checkpoint_key)
        existing = self._checkpoints.get(key)
        if existing == value:
            return existing
        self._checkpoints[key] = value
        return value

    def get_checkpoint(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> BackfillCheckpoint | None:
        return self._checkpoints.get((job_id, checkpoint_key))

    def list_checkpoints(self, job_id: str) -> tuple[BackfillCheckpoint, ...]:
        return tuple(
            self._checkpoints[key]
            for key in sorted(self._checkpoints)
            if key[0] == job_id
        )

    @staticmethod
    def _save_report(
        values: dict[str, _Report],
        report_id: str,
        value: _Report,
    ) -> _Report:
        existing = values.get(report_id)
        if existing is not None and existing != value:
            raise VersionConflictError(f"report identifier conflict: {report_id}")
        values[report_id] = value
        return value

    def save_quality_report(self, value: DatasetQualityReport) -> DatasetQualityReport:
        return self._save_report(self._quality, value.report_id, value)

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport:
        return self._save_report(self._coverage, value.report_id, value)

    def list_quality_reports(self) -> tuple[DatasetQualityReport, ...]:
        return tuple(self._quality[key] for key in sorted(self._quality))

    def list_coverage_reports(self) -> tuple[DatasetCoverageReport, ...]:
        return tuple(self._coverage[key] for key in sorted(self._coverage))
