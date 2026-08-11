"""Ports for evidence-bound provider-neutral financial backfill execution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol

from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    DatasetCoverageReport,
    DatasetQualityReport,
)
from a_share_platform.domain.disclosure import RawObject
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillWorkUnit,
    FinancialListingIdentity,
    FinancialMappingResult,
    FinancialPersistResult,
    FinancialProviderBatch,
)
from a_share_platform.domain.governance import LineageEdge


class FinancialEvidenceCapture(Protocol):
    def capture_provider_response(
        self,
        *,
        work_unit: FinancialBackfillWorkUnit,
        provider_id: str,
        source_url: str,
        provider_records: tuple[Mapping[str, object], ...],
        retrieved_at: datetime,
    ) -> RawObject: ...


class FinancialBackfillSource(Protocol):
    provider_id: str

    def fetch(
        self,
        work_unit: FinancialBackfillWorkUnit,
        *,
        allow_read_through_cache: bool,
    ) -> FinancialProviderBatch: ...


class FinancialIdentityResolver(Protocol):
    """Resolve provider symbols through effective-dated Security Master records."""

    def resolve(
        self,
        canonical_symbol: str,
        *,
        as_of: date,
    ) -> FinancialListingIdentity: ...


class FinancialBackfillUnitOfWork(Protocol):
    def get_checkpoint(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> BackfillCheckpoint | None: ...

    def save_checkpoint(self, value: BackfillCheckpoint) -> BackfillCheckpoint: ...

    def persist(self, value: FinancialMappingResult) -> FinancialPersistResult: ...

    def get_persist_result(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> FinancialPersistResult | None: ...

    def save_quality_report(self, value: DatasetQualityReport) -> DatasetQualityReport: ...

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport: ...

    def register_lineage(self, value: LineageEdge) -> LineageEdge: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
