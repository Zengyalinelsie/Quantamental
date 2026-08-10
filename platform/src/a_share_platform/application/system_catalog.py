"""Read models for the System data-management workspace."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True)
class DatasetCatalogEntry:
    dataset_version_id: str
    content_hash: str
    created_at: datetime
    schema_version: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityReportEntry:
    quality_report_id: str
    dataset_version_id: str
    job_id: str
    status: str
    checks_passed: int
    checks_failed: int
    issue_counts: dict[str, int]
    warnings: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class CoverageReportEntry:
    coverage_report_id: str
    dataset_version_id: str
    job_id: str
    scope_id: str
    data_domain: str
    start_date: date
    end_date: date
    expected_rows: int | None
    observed_rows: int
    coverage_ratio: float | None
    warnings: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class LineageCatalogEntry:
    upstream_id: str
    downstream_id: str
    relation: str


@dataclass(frozen=True)
class IngestionCheckpointEntry:
    checkpoint_key: str
    scope_id: str
    data_domain: str
    market: str | None
    status: str
    processed_rows: int
    rejected_rows: int
    provider_id: str | None
    updated_at: datetime
    error: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IngestionJobEntry:
    job_id: str
    plan_id: str
    provider_id: str
    status: str
    output_trust_state: str
    start_date: date
    end_date: date
    created_at: datetime
    updated_at: datetime
    dataset_version_id: str | None
    failure_reasons: tuple[str, ...]
    checkpoints: tuple[IngestionCheckpointEntry, ...]
    quality_reports: tuple[QualityReportEntry, ...]
    coverage_reports: tuple[CoverageReportEntry, ...]
