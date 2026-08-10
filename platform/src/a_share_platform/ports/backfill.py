"""Ports used by the provider-neutral data backfill application service."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillCheckpoint,
    BackfillJob,
    BackfillPlan,
    BackfillWorkUnit,
    DatasetCoverageReport,
    DatasetQualityReport,
)


class BackfillRepository(Protocol):
    def save_job(self, value: BackfillJob) -> BackfillJob: ...

    def append_job_state(self, value: BackfillJob) -> BackfillJob: ...

    def get_job(self, job_id: str) -> BackfillJob | None: ...

    def list_jobs(self) -> tuple[BackfillJob, ...]: ...

    def save_checkpoint(self, value: BackfillCheckpoint) -> BackfillCheckpoint: ...

    def get_checkpoint(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> BackfillCheckpoint | None: ...

    def list_checkpoints(self, job_id: str) -> tuple[BackfillCheckpoint, ...]: ...

    def save_quality_report(self, value: DatasetQualityReport) -> DatasetQualityReport: ...

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport: ...


class BackfillSource(Protocol):
    provider_id: str

    def fetch(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> BackfillBatch: ...


class BackfillSink(Protocol):
    def persist(self, batch: BackfillBatch, *, dataset_version_id: str) -> None: ...
