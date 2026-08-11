import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from a_share_platform.adapters.memory.disclosure import InMemoryDisclosureRepository
from a_share_platform.adapters.memory.financial_facts import InMemoryFinancialFactRepository
from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.adapters.memory.metrics import InMemoryMetricRegistryRepository
from a_share_platform.application.financial_facts import PITFinancialService
from a_share_platform.application.metric_registry import MetricRegistryService
from a_share_platform.domain.disclosure import (
    RawObject,
    RawObjectKind,
    RetentionPolicy,
)
from a_share_platform.domain.governance import DatasetVersion
from a_share_platform.domain.metrics import (
    CanonicalMetric,
    CurrencyRequirement,
    MappingMethod,
    MappingUseScope,
    MappingVersion,
    MetricUnit,
    ProviderFieldMapping,
    SignConvention,
    StatementType,
)
from a_share_platform.domain.pit import (
    AuthorityRule,
    DataQualityState,
    DataTrustState,
    FactObservation,
    FinancialPeriodType,
)
from a_share_platform.domain.run_context import DataMode

ANNOUNCED = datetime(2024, 3, 28, 10, tzinfo=UTC)
AVAILABLE = datetime(2024, 3, 28, 10, 1, tzinfo=UTC)
KNOWN = datetime(2024, 3, 28, 10, 5, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def raw_object(raw_object_id: str, provider_id: str, content_hash: str) -> RawObject:
    return RawObject(
        raw_object_id=raw_object_id,
        object_kind=RawObjectKind.FILE,
        content_hash=content_hash,
        source_url="https://www.cninfo.com.cn/disclosure/report.pdf",
        provider_id=provider_id,
        retrieved_at=KNOWN,
        media_type="application/pdf",
        storage_uri=f"file:///objects/{content_hash.removeprefix('sha256:')}",
        license_id="license:official-disclosure:v1",
        retention_policy=RetentionPolicy.INDEFINITE,
        retention_until=None,
        redistribution_allowed=False,
    )


def fact(
    *,
    fact_id: str = "fact:cninfo:revenue:2023:r0:system1",
    provider_id: str = "provider:cninfo",
    source_object_id: str = "raw:cninfo:report:v1",
    raw_object_hash: str = HASH_A,
    mapping_version_id: str = "metric-mapping:cninfo:v1",
    value: float = 100.0,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
    quality_state: DataQualityState = DataQualityState.PASSED,
    revision_sequence: int = 0,
    announced_at: datetime = ANNOUNCED,
    available_at: datetime = AVAILABLE,
    known_from: datetime = KNOWN,
    quality_issue_ids: tuple[str, ...] = (),
) -> FactObservation:
    return FactObservation(
        fact_id=fact_id,
        company_id="company:000001",
        security_id="security:000001-szse",
        metric_code="revenue",
        value=value,
        unit=MetricUnit.CURRENCY,
        currency="CNY",
        report_period_end=date(2023, 12, 31),
        period_type=FinancialPeriodType.ANNUAL,
        statement_type=StatementType.INCOME_STATEMENT,
        announced_at=announced_at,
        available_at=available_at,
        known_from=known_from,
        known_to=None,
        revision_sequence=revision_sequence,
        provider_id=provider_id,
        source_field="revenue",
        raw_object_hash=raw_object_hash,
        trust_state=trust_state,
        quality_state=quality_state,
        mapping_version_id=mapping_version_id,
        source_object_id=source_object_id,
        dataset_version_id="dataset:financials:v1",
        quality_issue_ids=quality_issue_ids,
    )


class PITFinancialServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = InMemoryFinancialFactRepository()
        self.disclosures = InMemoryDisclosureRepository()
        self.metrics = InMemoryMetricRegistryRepository()
        self.governance = InMemoryGovernanceRepository()
        self.disclosures.register_raw_object(
            raw_object("raw:cninfo:report:v1", "provider:cninfo", HASH_A)
        )
        self._register_provider_mapping("provider:cninfo", "metric-mapping:cninfo:v1", HASH_A)
        self.governance.register_dataset(
            DatasetVersion(
                dataset_version_id="dataset:financials:v1",
                content_hash=HASH_B,
                created_at=KNOWN,
                schema_version="financial-facts:v1",
            )
        )
        self.service = PITFinancialService(
            repository=self.facts,
            disclosure_repository=self.disclosures,
            metric_repository=self.metrics,
            governance_repository=self.governance,
        )

    def _ingest(
        self,
        value: FactObservation,
        *,
        use_scope: MappingUseScope = MappingUseScope.STRICT_HISTORICAL,
    ) -> FactObservation:
        return self.service.ingest(value, use_scope=use_scope)

    def _register_provider_mapping(
        self,
        provider_id: str,
        mapping_version_id: str,
        content_hash: str,
        allowed_use_scopes: frozenset[MappingUseScope] = frozenset(
            {
                MappingUseScope.CURRENT_RESEARCH,
                MappingUseScope.STRICT_HISTORICAL,
            }
        ),
    ) -> None:
        registry = MetricRegistryService(self.metrics)
        if self.metrics.get_metric("revenue") is None:
            registry.register_metric(
                CanonicalMetric(
                    metric_code="revenue",
                    canonical_name="Revenue",
                    statement_type=StatementType.INCOME_STATEMENT,
                    unit=MetricUnit.CURRENCY,
                    currency_requirement=CurrencyRequirement.REQUIRED,
                    sign_convention=SignConvention.NATURAL,
                    description="Operating revenue",
                )
            )
        registry.register_mapping_version(
            MappingVersion(
                mapping_version_id=mapping_version_id,
                provider_id=provider_id,
                created_at=KNOWN,
                content_hash=content_hash,
                code_version="git:abc123",
            )
        )
        registry.register_mapping(
            ProviderFieldMapping(
                mapping_id=f"mapping:{provider_id}:revenue:v1",
                mapping_version_id=mapping_version_id,
                provider_id=provider_id,
                statement_type=StatementType.INCOME_STATEMENT,
                source_field="revenue",
                metric_code="revenue",
                method=MappingMethod.EXACT,
                formula=None,
                allowed_use_scopes=allowed_use_scopes,
            )
        )

    def test_ingest_requires_matching_raw_evidence_mapping_and_registers_lineage(self) -> None:
        stored = self._ingest(fact())
        self.assertIs(stored, self.facts.get(stored.fact_id))
        self.assertEqual(
            {
                (edge.upstream_id, edge.downstream_id, edge.relation)
                for edge in self.governance.list_lineage()
            },
            {
                ("raw:cninfo:report:v1", stored.fact_id, "evidence_for"),
                ("metric-mapping:cninfo:v1", stored.fact_id, "mapped_by"),
                ("dataset:financials:v1", stored.fact_id, "contains"),
            },
        )
        with self.assertRaisesRegex(ValueError, "raw object hash"):
            self._ingest(
                fact(fact_id="fact:bad-hash", raw_object_hash=HASH_B)
            )
        with self.assertRaisesRegex(ValueError, "provider field mapping"):
            self._ingest(
                replace(fact(fact_id="fact:unmapped"), source_field="mystery")
            )

    def test_current_and_strict_queries_enforce_trust_and_both_clocks(self) -> None:
        current_only = self._ingest(
            fact(trust_state=DataTrustState.NORMALIZED_CURRENT),
            use_scope=MappingUseScope.CURRENT_RESEARCH,
        )
        strict = self.service.query(
            company_id=current_only.company_id,
            security_id=current_only.security_id,
            metric_code=current_only.metric_code,
            report_period_end=current_only.report_period_end,
            period_type=current_only.period_type,
            statement_type=current_only.statement_type,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=current_only.available_at,
            system_time=current_only.known_from,
            authority_rule=AuthorityRule("authority:v1", ("provider:cninfo",)),
        )
        current = self.service.query(
            company_id=current_only.company_id,
            security_id=current_only.security_id,
            metric_code=current_only.metric_code,
            report_period_end=current_only.report_period_end,
            period_type=current_only.period_type,
            statement_type=current_only.statement_type,
            data_mode=DataMode.CURRENT_RESEARCH,
            decision_time=current_only.available_at,
            system_time=current_only.known_from,
            authority_rule=AuthorityRule("authority:v1", ("provider:cninfo",)),
        )
        self.assertIsNone(strict.selected)
        self.assertIs(current.selected, current_only)

        backfilled = self._ingest(
            fact(
                fact_id="fact:late-backfill",
                known_from=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        before_warehouse = self.service.query_like(
            backfilled,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=datetime(2024, 4, 1, tzinfo=UTC),
            system_time=datetime(2025, 1, 1, tzinfo=UTC),
            authority_rule=AuthorityRule("authority:v1", ("provider:cninfo",)),
        )
        self.assertIsNone(before_warehouse.selected)

    def test_ingest_requires_mapping_scope_matching_fact_trust(self) -> None:
        provider_id = "provider:current-only"
        mapping_version_id = "metric-mapping:current-only:v1"
        self.disclosures.register_raw_object(
            raw_object("raw:current-only:report:v1", provider_id, HASH_B)
        )
        self._register_provider_mapping(
            provider_id,
            mapping_version_id,
            HASH_B,
            frozenset({MappingUseScope.CURRENT_RESEARCH}),
        )
        common = {
            "provider_id": provider_id,
            "source_object_id": "raw:current-only:report:v1",
            "raw_object_hash": HASH_B,
            "mapping_version_id": mapping_version_id,
        }

        stored = self._ingest(
            fact(
                fact_id="fact:current-only:normalized",
                trust_state=DataTrustState.NORMALIZED_CURRENT,
                **common,
            ),
            use_scope=MappingUseScope.CURRENT_RESEARCH,
        )
        self.assertIs(stored.trust_state, DataTrustState.NORMALIZED_CURRENT)
        with self.assertRaisesRegex(ValueError, "strict_historical"):
            self._ingest(
                fact(
                    fact_id="fact:current-only:pit",
                    trust_state=DataTrustState.PIT_VERIFIED,
                    **common,
                ),
                use_scope=MappingUseScope.STRICT_HISTORICAL,
            )

        production_provider = "provider:production-only"
        production_mapping_version = "metric-mapping:production-only:v1"
        self.disclosures.register_raw_object(
            raw_object(
                "raw:production-only:report:v1",
                production_provider,
                HASH_B,
            )
        )
        self._register_provider_mapping(
            production_provider,
            production_mapping_version,
            HASH_B,
            frozenset({MappingUseScope.PRODUCTION}),
        )
        production_fact = fact(
            fact_id="fact:production-only:pit",
            provider_id=production_provider,
            source_object_id="raw:production-only:report:v1",
            raw_object_hash=HASH_B,
            mapping_version_id=production_mapping_version,
        )
        stored_production = self._ingest(
            production_fact,
            use_scope=MappingUseScope.PRODUCTION,
        )
        self.assertIs(stored_production.trust_state, DataTrustState.PIT_VERIFIED)
        with self.assertRaisesRegex(ValueError, "current_research"):
            self._ingest(
                replace(
                    production_fact,
                    fact_id="fact:production-only:current-request",
                ),
                use_scope=MappingUseScope.CURRENT_RESEARCH,
            )

    def test_public_revision_changes_only_after_its_available_at(self) -> None:
        original = self._ingest(fact())
        revised = self._ingest(
            fact(
                fact_id="fact:cninfo:revenue:2023:r1:system1",
                value=90.0,
                revision_sequence=1,
                announced_at=ANNOUNCED + timedelta(days=30),
                available_at=AVAILABLE + timedelta(days=30),
            )
        )
        rule = AuthorityRule("authority:v1", ("provider:cninfo",))
        before = self.service.query_like(
            original,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=revised.available_at - timedelta(seconds=1),
            system_time=KNOWN,
            authority_rule=rule,
        )
        after = self.service.query_like(
            original,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=revised.available_at,
            system_time=KNOWN,
            authority_rule=rule,
        )
        self.assertIs(before.selected, original)
        self.assertIs(after.selected, revised)

    def test_multi_source_conflict_selects_versioned_authority_but_blocks_downstream(self) -> None:
        cninfo = self._ingest(fact())
        self.disclosures.register_raw_object(
            raw_object("raw:vendor:report:v1", "provider:vendor", HASH_B)
        )
        self._register_provider_mapping("provider:vendor", "metric-mapping:vendor:v1", HASH_B)
        vendor = self._ingest(
            fact(
                fact_id="fact:vendor:revenue:2023:r0:system1",
                provider_id="provider:vendor",
                source_object_id="raw:vendor:report:v1",
                raw_object_hash=HASH_B,
                mapping_version_id="metric-mapping:vendor:v1",
                value=101.0,
            )
        )
        selection = self.service.query_like(
            cninfo,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=AVAILABLE,
            system_time=KNOWN,
            authority_rule=AuthorityRule(
                "authority:official-first:v1",
                ("provider:cninfo", "provider:vendor"),
            ),
        )
        self.assertIs(selection.selected, cninfo)
        self.assertTrue(selection.blocks_downstream)
        self.assertEqual(selection.conflicting_fact_ids, (vendor.fact_id,))
        self.assertEqual(selection.authority_rule_version, "authority:official-first:v1")

    def test_system_correction_closes_old_interval_without_rewriting_history(self) -> None:
        original = self._ingest(fact())
        corrected = self._ingest(
            fact(
                fact_id="fact:cninfo:revenue:2023:r0:system2",
                value=99.0,
                known_from=KNOWN + timedelta(days=2),
            )
        )
        closed = self.facts.get(original.fact_id)
        self.assertEqual(closed.known_to, corrected.known_from)  # type: ignore[union-attr]
        rule = AuthorityRule("authority:v1", ("provider:cninfo",))
        before = self.service.query_like(
            original,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=AVAILABLE,
            system_time=corrected.known_from - timedelta(seconds=1),
            authority_rule=rule,
        )
        after = self.service.query_like(
            original,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=AVAILABLE,
            system_time=corrected.known_from,
            authority_rule=rule,
        )
        self.assertEqual(before.selected.fact_id, original.fact_id)  # type: ignore[union-attr]
        self.assertIs(after.selected, corrected)

    def test_blocked_quality_is_not_silently_selected(self) -> None:
        blocked = self._ingest(
            fact(
                quality_state=DataQualityState.BLOCKED,
                quality_issue_ids=("quality:balance-mismatch",),
            )
        )
        result = self.service.query_like(
            blocked,
            data_mode=DataMode.STRICT_HISTORICAL,
            decision_time=AVAILABLE,
            system_time=KNOWN,
            authority_rule=AuthorityRule("authority:v1", ("provider:cninfo",)),
        )
        self.assertIsNone(result.selected)
        self.assertTrue(result.blocks_downstream)
        self.assertEqual(result.quality_issue_ids, ("quality:balance-mismatch",))


if __name__ == "__main__":
    unittest.main()
