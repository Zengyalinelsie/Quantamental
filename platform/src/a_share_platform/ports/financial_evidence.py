"""Read-only port for disclosure, fact revision, and evidence diagnostics."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.application.financial_evidence import (
    DisclosureTimelineEntry,
    FactComparisonEntry,
    FactComparisonQuery,
    FactIdentityQuery,
    FactRevisionEntry,
    FinancialMismatchEntry,
    RawEvidenceEntry,
)


class FinancialEvidenceReader(Protocol):
    def list_disclosures(self, company_id: str | None = None) -> tuple[DisclosureTimelineEntry, ...]: ...

    def list_fact_revisions(self, query: FactIdentityQuery) -> tuple[FactRevisionEntry, ...]: ...

    def compare_fact(self, query: FactComparisonQuery) -> FactComparisonEntry | None: ...

    def list_mismatches(self) -> tuple[FinancialMismatchEntry, ...]: ...

    def get_evidence(self, raw_object_id: str) -> RawEvidenceEntry | None: ...
