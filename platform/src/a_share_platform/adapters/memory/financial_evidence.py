"""Static financial evidence reader for API and frontend contract tests."""

from __future__ import annotations

from dataclasses import dataclass

from a_share_platform.application.financial_evidence import (
    DisclosureTimelineEntry,
    FactComparisonEntry,
    FactComparisonQuery,
    FactIdentityQuery,
    FactRevisionEntry,
    FinancialMismatchEntry,
    RawEvidenceEntry,
)


@dataclass(frozen=True)
class StaticFinancialEvidenceReader:
    disclosures: tuple[DisclosureTimelineEntry, ...] = ()
    fact_revisions: tuple[FactRevisionEntry, ...] = ()
    comparisons: tuple[FactComparisonEntry, ...] = ()
    mismatches: tuple[FinancialMismatchEntry, ...] = ()
    evidence: tuple[RawEvidenceEntry, ...] = ()

    def list_disclosures(self, company_id: str | None = None) -> tuple[DisclosureTimelineEntry, ...]:
        return tuple(
            row for row in self.disclosures if company_id is None or row.company_id == company_id
        )

    def list_fact_revisions(self, query: FactIdentityQuery) -> tuple[FactRevisionEntry, ...]:
        return tuple(
            row
            for row in self.fact_revisions
            if (query.company_id is None or row.company_id == query.company_id)
            and (query.security_id is None or row.security_id == query.security_id)
            and (query.metric_code is None or row.metric_code == query.metric_code)
            and (
                query.report_period_end is None
                or row.report_period_end == query.report_period_end
            )
            and (query.period_type is None or row.period_type == query.period_type)
            and (query.statement_type is None or row.statement_type == query.statement_type)
        )

    def compare_fact(self, query: FactComparisonQuery) -> FactComparisonEntry | None:
        return next(
            (
                row
                for row in self.comparisons
                if row.company_id == query.company_id
                and row.security_id == query.security_id
                and row.metric_code == query.metric_code
                and row.report_period_end == query.report_period_end
                and row.period_type == query.period_type
                and row.statement_type == query.statement_type
                and row.authority_rule_version == query.authority_rule_version
            ),
            None,
        )

    def list_mismatches(self) -> tuple[FinancialMismatchEntry, ...]:
        return self.mismatches

    def get_evidence(self, raw_object_id: str) -> RawEvidenceEntry | None:
        return next((row for row in self.evidence if row.raw_object_id == raw_object_id), None)
