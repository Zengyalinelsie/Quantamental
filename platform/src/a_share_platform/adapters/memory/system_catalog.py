"""Deterministic read-only System catalog adapter for tests and empty runtime."""

from __future__ import annotations

from dataclasses import dataclass

from a_share_platform.application.system_catalog import (
    CoverageReportEntry,
    DatasetCatalogEntry,
    IngestionJobEntry,
    LineageCatalogEntry,
    QualityReportEntry,
)


@dataclass(frozen=True)
class StaticSystemCatalogReader:
    datasets: tuple[DatasetCatalogEntry, ...] = ()
    quality_reports: tuple[QualityReportEntry, ...] = ()
    coverage_reports: tuple[CoverageReportEntry, ...] = ()
    lineage: tuple[LineageCatalogEntry, ...] = ()
    jobs: tuple[IngestionJobEntry, ...] = ()

    def list_datasets(self) -> tuple[DatasetCatalogEntry, ...]:
        return self.datasets

    def list_quality_reports(self) -> tuple[QualityReportEntry, ...]:
        return self.quality_reports

    def list_lineage(self) -> tuple[LineageCatalogEntry, ...]:
        return self.lineage

    def list_jobs(self) -> tuple[IngestionJobEntry, ...]:
        return self.jobs
