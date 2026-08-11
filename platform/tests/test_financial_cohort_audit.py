import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from a_share_platform.application.financial_backfill import FinancialBackfillPlanner
from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.application.financial_cohort_audit import (
    FinancialCohortAuditService,
    FinancialCohortAuditSnapshot,
)
from a_share_platform.domain.backfill import BackfillJobStatus
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillCohort,
    FinancialBackfillPlan,
    FinancialStatementSelection,
)
from a_share_platform.domain.financial_sources import (
    FinancialSourceAccessMode,
    FinancialSourceProfile,
    FinancialSourceQualification,
    FinancialSourceRole,
)
from a_share_platform.domain.governance import DatasetVersion, LineageEdge
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)


def profile() -> FinancialSourceProfile:
    return FinancialSourceProfile(
        profile_version="financial-source:akshare:v1",
        provider_id="akshare",
        role=FinancialSourceRole.FALLBACK,
        markets=frozenset({"XSHG", "XSHE"}),
        statements=frozenset(StatementType),
        access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
        qualification=FinancialSourceQualification.NORMALIZED_CURRENT_APPROVED,
        trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
        retention_allowed=True,
        bulk_persistence_allowed=True,
        supplies_revision_history=False,
        supplies_exact_available_at=False,
        max_rows_per_request=100,
        warnings=("normalized_current only",),
    )


def job(suffix: str, symbols: tuple[str, ...], dataset_id: str) -> FinancialBackfillJobRecord:
    plan = FinancialBackfillPlan(
        plan_id=f"financial-backfill:csi500:{suffix}:v1",
        provider_id="akshare",
        provider_profile_version="financial-source:akshare:v1",
        cohort=FinancialBackfillCohort.CSI_500,
        universe_version_id="universe:index-000905:2026-08-10:v1",
        mapping_version_id="metric-mapping:akshare-eastmoney:v1",
        statements=(
            FinancialStatementSelection(StatementType.BALANCE_SHEET, "balance_sheet"),
            FinancialStatementSelection(StatementType.INCOME_STATEMENT, "income_statement"),
            FinancialStatementSelection(StatementType.CASH_FLOW_STATEMENT, "cash_flow"),
        ),
        report_period_ends=(date(2024, 12, 31), date(2025, 12, 31)),
        symbols=symbols,
        symbol_bucket_size=1,
        created_at=NOW,
        data_mode=DataMode.CURRENT_RESEARCH,
        output_trust_state=DataTrustState.NORMALIZED_CURRENT,
        allow_read_through_cache=True,
        bulk_persistence_acknowledged=True,
        predecessor_coverage_report_id="coverage:csi300:qualified:v1",
    )
    initial = FinancialBackfillJobRecord.initial(
        FinancialBackfillPlanner().preview(plan, profile())
    )
    return replace(
        initial,
        status=BackfillJobStatus.SUCCEEDED,
        updated_at=NOW + timedelta(minutes=2),
        dataset_version_id=dataset_id,
    )


class MemoryRepository:
    def __init__(self) -> None:
        values = (
            job("pilot", ("SH.600000",), "dataset:component:pilot"),
            job("remaining", ("SZ.000001",), "dataset:component:remaining"),
        )
        self.jobs = {value.job_id: value for value in values}
        self.snapshot = FinancialCohortAuditSnapshot(
            job_ids=tuple(sorted(self.jobs)),
            completed_work_units=12,
            receipt_observation_count=30,
            persisted_observation_count=30,
            zero_observation_work_units=2,
            rejected_rows=0,
            observed_symbols=("SH.600000", "SZ.000001"),
            coverage_report_count=12,
            full_coverage_reports=10,
            partial_coverage_reports=0,
            zero_coverage_reports=2,
            quality_report_count=12,
            passed_quality_reports=10,
            warned_quality_reports=2,
            failed_quality_reports=0,
            quality_issue_counts=(("missing_security", 2),),
            completed_at=NOW + timedelta(minutes=3),
        )
        self.datasets: dict[str, tuple[DatasetVersion, dict[str, object]]] = {}
        self.lineage: set[LineageEdge] = set()
        self.commits = 0
        self.rollbacks = 0

    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None:
        return self.jobs.get(job_id)

    def get_snapshot(self, job_ids: tuple[str, ...]) -> FinancialCohortAuditSnapshot:
        self.requested_job_ids = job_ids
        return self.snapshot

    def get_dataset_metadata(self, dataset_version_id: str) -> dict[str, object] | None:
        stored = self.datasets.get(dataset_version_id)
        return None if stored is None else stored[1]

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: dict[str, object],
    ) -> DatasetVersion:
        self.datasets.setdefault(value.dataset_version_id, (value, metadata))
        return self.datasets[value.dataset_version_id][0]

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        self.lineage.add(value)
        return value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FinancialCohortAuditServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = MemoryRepository()
        self.service = FinancialCohortAuditService(self.repository)
        self.job_ids = tuple(sorted(self.repository.jobs))

    def test_evidence_freezes_combined_coverage_quality_and_trust(self) -> None:
        evidence = self.service.evaluate(
            job_ids=self.job_ids,
            expected_security_count=2,
        )

        self.assertEqual(evidence.expected_work_units, 12)
        self.assertEqual(evidence.completed_work_units, 12)
        self.assertEqual(evidence.observation_count, 30)
        self.assertEqual(evidence.security_count, 2)
        manifest = evidence.metadata["manifest"]
        self.assertEqual(manifest["coverage"]["ratio"], 1.0)  # type: ignore[index]
        self.assertEqual(manifest["coverage"]["full_reports"], 10)  # type: ignore[index]
        self.assertEqual(manifest["coverage"]["zero_reports"], 2)  # type: ignore[index]
        self.assertEqual(manifest["quality"]["status"], "warned")  # type: ignore[index]
        self.assertEqual(manifest["quality"]["empty_work_units"], 2)  # type: ignore[index]
        self.assertEqual(manifest["data_mode"], "current_research")  # type: ignore[index]
        self.assertEqual(manifest["trust_state"], "normalized_current")  # type: ignore[index]
        self.assertFalse(manifest["pit_verified"])  # type: ignore[index]
        self.assertEqual(len(evidence.lineage), 4)

    def test_ensure_is_idempotent_and_registers_component_scope_and_mapping_lineage(self) -> None:
        first = self.service.ensure(job_ids=self.job_ids, expected_security_count=2)
        second = self.service.ensure(job_ids=self.job_ids, expected_security_count=2)

        self.assertTrue(first.writes_performed)
        self.assertFalse(second.writes_performed)
        self.assertEqual(first.evidence, second.evidence)
        self.assertEqual(len(self.repository.datasets), 1)
        relations = {edge.relation for edge in self.repository.lineage}
        self.assertEqual(relations, {"aggregated_into", "mapped_by", "scoped_by"})
        self.assertEqual(self.repository.commits, 2)
        self.assertEqual(self.repository.rollbacks, 0)

    def test_overlap_incomplete_counts_or_failed_quality_fail_closed(self) -> None:
        remaining_id = next(job_id for job_id in self.job_ids if "remaining" in job_id)
        remaining = self.repository.jobs[remaining_id]
        overlap_plan = replace(remaining.plan, symbols=("SH.600000",))
        self.repository.jobs[remaining_id] = replace(remaining, plan=overlap_plan)
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.service.evaluate(job_ids=self.job_ids, expected_security_count=2)

        self.repository = MemoryRepository()
        self.service = FinancialCohortAuditService(self.repository)
        self.repository.snapshot = replace(self.repository.snapshot, completed_work_units=11)
        with self.assertRaisesRegex(ValueError, "completed_work_units"):
            self.service.evaluate(job_ids=self.job_ids, expected_security_count=2)

        self.repository.snapshot = replace(
            self.repository.snapshot,
            completed_work_units=12,
            passed_quality_reports=9,
            failed_quality_reports=1,
        )
        with self.assertRaisesRegex(ValueError, "failed quality"):
            self.service.evaluate(job_ids=self.job_ids, expected_security_count=2)


if __name__ == "__main__":
    unittest.main()
