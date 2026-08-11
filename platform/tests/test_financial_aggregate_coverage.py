import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from a_share_platform.application.financial_aggregate_coverage import (
    FinancialAggregateCoverageService,
    FinancialAggregateCoverageSnapshot,
)
from a_share_platform.application.financial_backfill import FinancialBackfillPlanner
from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.domain.backfill import BackfillJobStatus, DatasetCoverageReport
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
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

NOW = datetime(2026, 8, 11, 5, tzinfo=UTC)


def plan() -> FinancialBackfillPlan:
    return FinancialBackfillPlan(
        plan_id="financial-backfill:csi300:aggregate-coverage-test:v1",
        provider_id="akshare",
        provider_profile_version="financial-source:akshare:v1",
        cohort=FinancialBackfillCohort.CSI_300,
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="metric-mapping:akshare-eastmoney:v1",
        statements=(FinancialStatementSelection(StatementType.BALANCE_SHEET, "balance_sheet"),),
        report_period_ends=(date(2023, 12, 31), date(2024, 12, 31)),
        symbols=("SH.600000",),
        symbol_bucket_size=1,
        created_at=NOW,
        data_mode=DataMode.CURRENT_RESEARCH,
        output_trust_state=DataTrustState.NORMALIZED_CURRENT,
        allow_read_through_cache=True,
        bulk_persistence_acknowledged=True,
    )


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


def succeeded_job() -> FinancialBackfillJobRecord:
    preview = FinancialBackfillPlanner().preview(plan(), profile())
    initial = FinancialBackfillJobRecord.initial(preview)
    return replace(
        initial,
        status=BackfillJobStatus.SUCCEEDED,
        updated_at=NOW + timedelta(minutes=3),
        dataset_version_id="dataset:financial:aggregate:v1",
    )


class InMemoryAggregateCoverageRepository:
    def __init__(self) -> None:
        self.job = succeeded_job()
        self.snapshot = FinancialAggregateCoverageSnapshot(
            job_id=self.job.job_id,
            completed_work_units=2,
            receipt_observation_count=3,
            persisted_observation_count=3,
            observed_symbols=("SH.600000",),
            completed_at=NOW + timedelta(minutes=2),
        )
        self.reports: dict[str, DatasetCoverageReport] = {}
        self.commits = 0
        self.rollbacks = 0

    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None:
        return self.job if job_id == self.job.job_id else None

    def get_snapshot(self, _job_id: str) -> FinancialAggregateCoverageSnapshot:
        return self.snapshot

    def get_coverage_report(self, report_id: str) -> DatasetCoverageReport | None:
        return self.reports.get(report_id)

    def save_coverage_report(self, value: DatasetCoverageReport) -> DatasetCoverageReport:
        self.reports.setdefault(value.report_id, value)
        return self.reports[value.report_id]

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FinancialAggregateCoverageServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryAggregateCoverageRepository()
        self.service = FinancialAggregateCoverageService(self.repository)

    def test_report_binds_units_symbols_observations_and_aggregate_dataset(self) -> None:
        evidence = self.service.evaluate(self.repository.job.job_id)

        self.assertEqual(evidence.expected_work_units, 2)
        self.assertEqual(evidence.completed_work_units, 2)
        self.assertEqual(evidence.expected_security_count, 1)
        self.assertEqual(evidence.observed_security_count, 1)
        self.assertEqual(evidence.canonical_observation_count, 3)
        self.assertEqual(evidence.report.dataset_version_id, "dataset:financial:aggregate:v1")
        self.assertEqual(evidence.report.expected_rows, 2)
        self.assertEqual(evidence.report.observed_rows, 2)
        self.assertEqual(evidence.report.coverage_ratio, 1.0)
        self.assertIn("coverage_basis=completed_financial_work_units", evidence.report.warnings)
        self.assertIn("canonical_observation_count=3", evidence.report.warnings)
        self.assertIn("pit_verified=false", evidence.report.warnings)

    def test_persist_is_idempotent_and_verifies_stored_report(self) -> None:
        first = self.service.ensure(self.repository.job.job_id)
        second = self.service.ensure(self.repository.job.job_id)

        self.assertTrue(first.writes_performed)
        self.assertFalse(second.writes_performed)
        self.assertEqual(first.evidence, second.evidence)
        self.assertEqual(len(self.repository.reports), 1)
        self.assertEqual(self.repository.commits, 1)
        self.assertEqual(self.repository.rollbacks, 0)

    def test_incomplete_units_or_observation_mismatch_fail_closed(self) -> None:
        invalid_snapshots = (
            replace(self.repository.snapshot, completed_work_units=1),
            replace(self.repository.snapshot, persisted_observation_count=2),
            replace(self.repository.snapshot, observed_symbols=()),
        )
        for snapshot in invalid_snapshots:
            with self.subTest(snapshot=snapshot):
                self.repository.snapshot = snapshot
                with self.assertRaises(ValueError):
                    self.service.evaluate(self.repository.job.job_id)

    def test_only_succeeded_csi300_current_research_job_can_be_predecessor(self) -> None:
        self.repository.job = replace(
            self.repository.job,
            status=BackfillJobStatus.RUNNING,
            dataset_version_id=None,
        )
        with self.assertRaisesRegex(ValueError, "succeeded"):
            self.service.evaluate(self.repository.job.job_id)

        self.repository.job = succeeded_job()
        csi500_plan = replace(
            self.repository.job.plan,
            cohort=FinancialBackfillCohort.CSI_500,
            predecessor_coverage_report_id="coverage:real:csi300:v1",
        )
        self.repository.job = replace(self.repository.job, plan=csi500_plan)
        with self.assertRaisesRegex(ValueError, "CSI300"):
            self.service.evaluate(self.repository.job.job_id)


if __name__ == "__main__":
    unittest.main()
