"""Read-only port for data-management catalog views."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.application.system_catalog import (
    DatasetCatalogEntry,
    IngestionJobEntry,
    LineageCatalogEntry,
    QualityReportEntry,
)


class SystemCatalogReader(Protocol):
    def list_datasets(self) -> tuple[DatasetCatalogEntry, ...]: ...

    def list_quality_reports(self) -> tuple[QualityReportEntry, ...]: ...

    def list_lineage(self) -> tuple[LineageCatalogEntry, ...]: ...

    def list_jobs(self) -> tuple[IngestionJobEntry, ...]: ...
