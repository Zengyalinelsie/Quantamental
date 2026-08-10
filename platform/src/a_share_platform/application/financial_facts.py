"""Ingestion and bitemporal selection of canonical financial facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from a_share_platform.domain.governance import LineageEdge, VersionConflictError
from a_share_platform.domain.metrics import MappingMethod, MetricUnit, StatementType
from a_share_platform.domain.pit import (
    AuthorityRule,
    FactObservation,
    FactSelection,
    FinancialPeriodType,
    PointInTimeConflictError,
    select_fact_as_of,
)
from a_share_platform.domain.run_context import DataMode
from a_share_platform.ports.disclosure import DisclosureRepository
from a_share_platform.ports.financial_facts import FinancialFactRepository
from a_share_platform.ports.governance import GovernanceRepository
from a_share_platform.ports.metrics import MetricRegistryRepository


class PITFinancialService:
    def __init__(
        self,
        *,
        repository: FinancialFactRepository,
        disclosure_repository: DisclosureRepository,
        metric_repository: MetricRegistryRepository,
        governance_repository: GovernanceRepository,
    ) -> None:
        self._repository = repository
        self._disclosures = disclosure_repository
        self._metrics = metric_repository
        self._governance = governance_repository

    def ingest(self, value: FactObservation) -> FactObservation:
        """Validate evidence, mapping, dataset lineage, then append one fact version."""

        existing_by_id = self._repository.get(value.fact_id)
        if existing_by_id is not None:
            if existing_by_id != value:
                raise VersionConflictError(
                    f"immutable financial fact identifier conflict: {value.fact_id}"
                )
            return existing_by_id

        raw = self._disclosures.get_raw_object(value.source_object_id)
        if raw is None:
            raise ValueError(f"raw object does not exist: {value.source_object_id}")
        if raw.content_hash != value.raw_object_hash:
            raise ValueError("raw object hash does not match financial fact")
        if raw.provider_id != value.provider_id:
            raise ValueError("raw object provider does not match financial fact")

        metric = self._metrics.get_metric(value.metric_code)
        if metric is None:
            raise ValueError(f"canonical metric does not exist: {value.metric_code}")
        if metric.statement_type is not value.statement_type:
            raise ValueError("financial fact statement type does not match canonical metric")
        if metric.unit is not value.unit:
            raise ValueError("financial fact unit does not match canonical metric")
        if (
            value.unit in {MetricUnit.CURRENCY, MetricUnit.CURRENCY_PER_SHARE}
            and value.currency is None
        ):  # defensive; domain constructor already checks this
            raise ValueError("currency-valued financial fact requires currency")

        mapping_version = self._metrics.get_mapping_version(value.mapping_version_id)
        if mapping_version is None:
            raise ValueError(f"mapping version does not exist: {value.mapping_version_id}")
        if mapping_version.provider_id != value.provider_id:
            raise ValueError("mapping version provider does not match financial fact")
        mappings = self._metrics.find_mappings(
            provider_id=value.provider_id,
            statement_type=value.statement_type,
            source_field=value.source_field,
            mapping_version_id=value.mapping_version_id,
        )
        valid_mappings = tuple(
            mapping
            for mapping in mappings
            if mapping.metric_code == value.metric_code
            and mapping.production_allowed
            and mapping.method is not MappingMethod.FUZZY
        )
        if len(valid_mappings) != 1:
            raise ValueError("exactly one production provider field mapping is required")

        if not any(
            dataset.dataset_version_id == value.dataset_version_id
            for dataset in self._governance.list_datasets()
        ):
            raise ValueError(f"dataset version does not exist: {value.dataset_version_id}")

        observations = self._repository.find(
            company_id=value.company_id,
            security_id=value.security_id,
            metric_code=value.metric_code,
            report_period_end=value.report_period_end,
            period_type=value.period_type,
            statement_type=value.statement_type,
        )
        same_source_revision = tuple(
            row
            for row in observations
            if row.provider_id == value.provider_id
            and row.revision_sequence == value.revision_sequence
            and row.known_to is None
        )
        if len(same_source_revision) > 1:
            raise PointInTimeConflictError(
                "multiple open system versions exist for one provider revision"
            )
        if same_source_revision:
            previous = same_source_revision[0]
            if (previous.announced_at, previous.available_at) != (
                value.announced_at,
                value.available_at,
            ):
                raise VersionConflictError(
                    "system correction cannot change public revision timestamps"
                )
            if value.known_from <= previous.known_from:
                raise VersionConflictError(
                    "system correction known_from must follow the open system version"
                )
            self._repository.close_system_interval(previous.fact_id, value.known_from)

        stored = self._repository.save(value)
        for upstream_id, relation in (
            (value.source_object_id, "evidence_for"),
            (value.mapping_version_id, "mapped_by"),
            (value.dataset_version_id, "contains"),
        ):
            self._governance.register_lineage(
                LineageEdge(
                    upstream_id=upstream_id,
                    downstream_id=stored.fact_id,
                    relation=relation,
                )
            )
        return stored

    def query(
        self,
        *,
        company_id: str,
        security_id: str,
        metric_code: str,
        report_period_end: date,
        period_type: FinancialPeriodType,
        statement_type: StatementType,
        data_mode: DataMode,
        decision_time: datetime,
        system_time: datetime,
        authority_rule: AuthorityRule,
    ) -> FactSelection:
        rows = self._repository.find(
            company_id=company_id,
            security_id=security_id,
            metric_code=metric_code,
            report_period_end=report_period_end,
            period_type=period_type,
            statement_type=statement_type,
        )
        by_provider: dict[str, list[FactObservation]] = defaultdict(list)
        for row in rows:
            by_provider[row.provider_id].append(row)

        provider_winners: dict[str, FactObservation] = {}
        quality_issues: set[str] = set()
        quality_blocked = False
        had_time_eligible = False
        for provider_id, observations in by_provider.items():
            winner = select_fact_as_of(
                observations,
                data_mode,
                decision_time=decision_time,
                system_time=system_time,
            )
            if winner is None:
                continue
            had_time_eligible = True
            quality_issues.update(winner.quality_issue_ids)
            if winner.quality_state.blocks_downstream:
                quality_blocked = True
                continue
            provider_winners[provider_id] = winner

        selected = next(
            (
                provider_winners[provider]
                for provider in authority_rule.provider_priority
                if provider in provider_winners
            ),
            None,
        )
        conflicts: tuple[str, ...] = ()
        if selected is not None:
            conflicts = tuple(
                sorted(
                    winner.fact_id
                    for winner in provider_winners.values()
                    if winner.fact_id != selected.fact_id
                    and winner.semantic_value != selected.semantic_value
                )
            )
        elif provider_winners:
            # Values exist, but the versioned rule has no authority for their providers.
            conflicts = tuple(sorted(winner.fact_id for winner in provider_winners.values()))

        blocks = quality_blocked or bool(conflicts)
        if rows and selected is None and not had_time_eligible:
            blocks = True
        return FactSelection(
            selected=selected,
            conflicting_fact_ids=conflicts,
            quality_issue_ids=tuple(sorted(quality_issues)),
            authority_rule_version=authority_rule.rule_version,
            blocks_downstream=blocks,
        )

    def query_like(
        self,
        value: FactObservation,
        *,
        data_mode: DataMode,
        decision_time: datetime,
        system_time: datetime,
        authority_rule: AuthorityRule,
    ) -> FactSelection:
        return self.query(
            company_id=value.company_id,
            security_id=value.security_id,
            metric_code=value.metric_code,
            report_period_end=value.report_period_end,
            period_type=value.period_type,
            statement_type=value.statement_type,
            data_mode=data_mode,
            decision_time=decision_time,
            system_time=system_time,
            authority_rule=authority_rule,
        )
