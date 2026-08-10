"""Read models and selection logic for auditable financial evidence views."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from a_share_platform.domain.pit import (
    AuthorityRule,
    DataMode,
    FactObservation,
    FactValue,
    select_fact_as_of,
)


@dataclass(frozen=True)
class RawEvidenceEntry:
    raw_object_id: str
    object_kind: str
    content_hash: str
    source_url: str
    provider_id: str
    retrieved_at: datetime
    media_type: str
    license_id: str
    retention_policy: str
    retention_until: date | None
    redistribution_allowed: bool


@dataclass(frozen=True)
class DisclosureTimelineEntry:
    disclosure_id: str
    document_key: str
    external_document_id: str
    company_id: str
    security_id: str | None
    source_system: str
    title: str
    document_type: str
    report_period_end: date | None
    published_at: datetime
    available_at: datetime
    first_tradable_at: datetime
    publication_time_precision: str
    version_sequence: int
    status: str
    raw_object_id: str
    supersedes_disclosure_id: str | None
    status_reason: str | None


@dataclass(frozen=True)
class FactRevisionEntry:
    fact_id: str
    company_id: str
    security_id: str
    metric_code: str
    value: FactValue
    unit: str
    currency: str | None
    report_period_end: date
    period_type: str
    statement_type: str
    announced_at: datetime
    available_at: datetime
    known_from: datetime
    known_to: datetime | None
    revision_sequence: int
    provider_id: str
    source_field: str
    trust_state: str
    quality_state: str
    mapping_version_id: str
    source_object_id: str
    dataset_version_id: str
    quality_issue_ids: tuple[str, ...]


@dataclass(frozen=True)
class FactSelectionEntry:
    status: Literal["selected", "unavailable", "blocked"]
    selected: FactRevisionEntry | None
    conflicting_fact_ids: tuple[str, ...]
    quality_issue_ids: tuple[str, ...]
    blocks_downstream: bool
    reason: str | None


@dataclass(frozen=True)
class FactComparisonEntry:
    company_id: str
    security_id: str
    metric_code: str
    report_period_end: date
    period_type: str
    statement_type: str
    decision_time: datetime
    system_time: datetime
    authority_rule_version: str
    current: FactSelectionEntry
    strict: FactSelectionEntry


@dataclass(frozen=True)
class FinancialMismatchEntry:
    mismatch_id: str
    mismatch_type: str
    status: str
    company_id: str | None
    security_id: str | None
    metric_code: str | None
    report_period_end: date | None
    provider_ids: tuple[str, ...]
    related_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class FactIdentityQuery:
    company_id: str | None = None
    security_id: str | None = None
    metric_code: str | None = None
    report_period_end: date | None = None
    period_type: str | None = None
    statement_type: str | None = None


@dataclass(frozen=True)
class FactComparisonQuery:
    company_id: str
    security_id: str
    metric_code: str
    report_period_end: date
    period_type: str
    statement_type: str
    decision_time: datetime
    system_time: datetime
    authority_rule_version: str


def fact_entry(value: FactObservation) -> FactRevisionEntry:
    return FactRevisionEntry(
        fact_id=value.fact_id,
        company_id=value.company_id,
        security_id=value.security_id,
        metric_code=value.metric_code,
        value=value.value,
        unit=value.unit.value,
        currency=value.currency,
        report_period_end=value.report_period_end,
        period_type=value.period_type.value,
        statement_type=value.statement_type.value,
        announced_at=value.announced_at,
        available_at=value.available_at,
        known_from=value.known_from,
        known_to=value.known_to,
        revision_sequence=value.revision_sequence,
        provider_id=value.provider_id,
        source_field=value.source_field,
        trust_state=value.trust_state.value,
        quality_state=value.quality_state.value,
        mapping_version_id=value.mapping_version_id,
        source_object_id=value.source_object_id,
        dataset_version_id=value.dataset_version_id,
        quality_issue_ids=value.quality_issue_ids,
    )


def compare_fact_modes(
    observations: tuple[FactObservation, ...],
    query: FactComparisonQuery,
    authority_rule: AuthorityRule,
) -> FactComparisonEntry:
    if authority_rule.rule_version != query.authority_rule_version:
        raise ValueError("authority rule version does not match comparison query")
    return FactComparisonEntry(
        company_id=query.company_id,
        security_id=query.security_id,
        metric_code=query.metric_code,
        report_period_end=query.report_period_end,
        period_type=query.period_type,
        statement_type=query.statement_type,
        decision_time=query.decision_time,
        system_time=query.system_time,
        authority_rule_version=query.authority_rule_version,
        current=_select(observations, query, authority_rule, DataMode.CURRENT_RESEARCH),
        strict=_select(observations, query, authority_rule, DataMode.STRICT_HISTORICAL),
    )


def _select(
    observations: tuple[FactObservation, ...],
    query: FactComparisonQuery,
    authority_rule: AuthorityRule,
    data_mode: DataMode,
) -> FactSelectionEntry:
    by_provider: defaultdict[str, list[FactObservation]] = defaultdict(list)
    for row in observations:
        by_provider[row.provider_id].append(row)
    winners: dict[str, FactObservation] = {}
    issues: set[str] = set()
    quality_blocked = False
    for provider_id, rows in by_provider.items():
        winner = select_fact_as_of(
            rows,
            data_mode,
            decision_time=query.decision_time,
            system_time=query.system_time,
        )
        if winner is None:
            continue
        issues.update(winner.quality_issue_ids)
        if winner.quality_state.blocks_downstream:
            quality_blocked = True
        else:
            winners[provider_id] = winner
    selected = next(
        (winners[provider] for provider in authority_rule.provider_priority if provider in winners),
        None,
    )
    conflicts = () if selected is None else tuple(
        sorted(
            row.fact_id
            for row in winners.values()
            if row.fact_id != selected.fact_id and row.semantic_value != selected.semantic_value
        )
    )
    blocks = quality_blocked or bool(conflicts)
    if selected is None:
        reason = (
            "no pit_verified observation is eligible"
            if data_mode is DataMode.STRICT_HISTORICAL
            else "no normalized_current or pit_verified observation is eligible"
        )
        return FactSelectionEntry(
            status="blocked" if quality_blocked else "unavailable",
            selected=None,
            conflicting_fact_ids=conflicts,
            quality_issue_ids=tuple(sorted(issues)),
            blocks_downstream=True,
            reason=reason,
        )
    return FactSelectionEntry(
        status="blocked" if blocks else "selected",
        selected=fact_entry(selected),
        conflicting_fact_ids=conflicts,
        quality_issue_ids=tuple(sorted(issues)),
        blocks_downstream=blocks,
        reason="provider values conflict or quality blocks downstream" if blocks else None,
    )
