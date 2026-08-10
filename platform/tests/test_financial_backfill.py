import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from a_share_platform.application.financial_backfill import FinancialBackfillPlanner
from a_share_platform.domain.backfill import (
    BackfillCheckpointStatus,
    BackfillDataDomain,
    DatasetQualityStatus,
)
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillBatchResult,
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

NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def source_profile(
    *,
    qualification: FinancialSourceQualification = (
        FinancialSourceQualification.NORMALIZED_CURRENT_APPROVED
    ),
) -> FinancialSourceProfile:
    return FinancialSourceProfile(
        profile_version="financial-source:factor-service-ths:v1",
        provider_id="factor_service_ths",
        role=FinancialSourceRole.PRIMARY,
        markets=frozenset({"XSHG", "XSHE"}),
        statements=frozenset(StatementType),
        access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
        qualification=qualification,
        trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
        retention_allowed=True,
        bulk_persistence_allowed=True,
        supplies_revision_history=False,
        supplies_exact_available_at=False,
        max_rows_per_request=5000,
        warnings=("current-only source",),
    )


def plan(**overrides: object) -> FinancialBackfillPlan:
    values: dict[str, object] = {
        "plan_id": "financial-backfill:csi300:2018q1-2018q2:v1",
        "provider_id": "factor_service_ths",
        "provider_profile_version": "financial-source:factor-service-ths:v1",
        "cohort": FinancialBackfillCohort.CSI_300,
        "universe_version_id": "universe:index-000300:2026-08-10:v1",
        "mapping_version_id": "mapping:factor-service-ths:a-share-financials:v1",
        "statements": (
            FinancialStatementSelection(
                StatementType.BALANCE_SHEET,
                "balance_sheet",
            ),
            FinancialStatementSelection(
                StatementType.INCOME_STATEMENT,
                "income_statement",
            ),
            FinancialStatementSelection(
                StatementType.CASH_FLOW_STATEMENT,
                "cash_flow",
            ),
        ),
        "report_period_ends": (date(2018, 3, 31), date(2018, 6, 30)),
        "symbols": ("SZ.000001", "SH.600000", "SZ.000002"),
        "symbol_bucket_size": 2,
        "created_at": NOW,
        "data_mode": DataMode.CURRENT_RESEARCH,
        "output_trust_state": DataTrustState.NORMALIZED_CURRENT,
        "allow_read_through_cache": True,
        "bulk_persistence_acknowledged": True,
        "predecessor_coverage_report_id": None,
    }
    values.update(overrides)
    return FinancialBackfillPlan(**values)  # type: ignore[arg-type]


class FinancialBackfillPlanTest(unittest.TestCase):
    def test_plan_is_current_only_and_csi500_requires_csi300_coverage(self) -> None:
        with self.assertRaisesRegex(ValueError, "current_research"):
            plan(data_mode=DataMode.STRICT_HISTORICAL)
        with self.assertRaisesRegex(ValueError, "normalized_current"):
            plan(output_trust_state=DataTrustState.PIT_VERIFIED)
        with self.assertRaisesRegex(ValueError, "CSI300 coverage"):
            plan(cohort=FinancialBackfillCohort.CSI_500)

        csi500 = plan(
            cohort=FinancialBackfillCohort.CSI_500,
            universe_version_id="universe:index-000905:2026-08-10:v1",
            predecessor_coverage_report_id="coverage:financial:csi300:v1",
        )
        self.assertEqual(csi500.benchmark_id, "index:000905")

    def test_plan_freezes_unique_canonical_symbols_periods_and_statement_tables(self) -> None:
        value = plan()
        self.assertEqual(value.symbols, ("SH.600000", "SZ.000001", "SZ.000002"))
        with self.assertRaisesRegex(ValueError, "canonical"):
            plan(symbols=("600000",))
        with self.assertRaisesRegex(ValueError, "unique"):
            plan(report_period_ends=(date(2018, 3, 31), date(2018, 3, 31)))
        with self.assertRaisesRegex(ValueError, "provider tables"):
            plan(
                statements=(
                    FinancialStatementSelection(
                        StatementType.BALANCE_SHEET,
                        "balance_sheet",
                    ),
                    FinancialStatementSelection(
                        StatementType.INCOME_STATEMENT,
                        "balance_sheet",
                    ),
                )
            )


class FinancialBackfillPlannerTest(unittest.TestCase):
    def test_work_units_are_deterministic_provider_table_period_symbol_buckets(self) -> None:
        planner = FinancialBackfillPlanner()
        first = planner.preview(plan(), source_profile())
        second = planner.preview(plan(), source_profile())

        self.assertTrue(first.qualification.permitted)
        self.assertEqual(first.work_units, second.work_units)
        self.assertEqual(len(first.work_units), 12)
        self.assertEqual(len({unit.checkpoint_key for unit in first.work_units}), 12)
        first_unit = first.work_units[0]
        self.assertEqual(first_unit.provider_id, "factor_service_ths")
        self.assertEqual(first_unit.report_period_end, date(2018, 3, 31))
        self.assertLessEqual(len(first_unit.symbols), 2)

    def test_candidate_missing_ack_and_profile_mismatch_fail_closed_without_io(self) -> None:
        planner = FinancialBackfillPlanner()
        candidate = planner.preview(
            plan(bulk_persistence_acknowledged=False),
            source_profile(qualification=FinancialSourceQualification.CANDIDATE),
        )
        self.assertFalse(candidate.qualification.permitted)
        self.assertTrue(any("candidate" in item for item in candidate.qualification.blockers))
        self.assertTrue(any("acknowledged" in item for item in candidate.qualification.blockers))

        mismatch = planner.preview(
            plan(),
            replace(source_profile(), provider_id="wind"),
        )
        self.assertFalse(mismatch.qualification.permitted)
        self.assertTrue(any("provider_id" in item for item in mismatch.qualification.blockers))

    def test_result_reuses_checkpoint_quality_and_coverage_ledgers(self) -> None:
        planner = FinancialBackfillPlanner()
        unit = planner.preview(plan(), source_profile()).work_units[0]
        pending = planner.pending_checkpoint(job_id="job:financial:csi300:v1", unit=unit, at=NOW)
        running = pending.transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        result = FinancialBackfillBatchResult(
            work_unit=unit,
            retrieved_at=NOW,
            provider_cutoff_date=date(2026, 8, 10),
            content_hash=HASH,
            processed_provider_rows=100,
            canonical_observations=95,
            rejected_rows=5,
            accepted_symbols=(unit.symbols[0],),
            quality_status=DatasetQualityStatus.WARNED,
            issue_counts=(("unmapped_field", 5),),
            warnings=("one security missing",),
        )

        succeeded = planner.complete_checkpoint(running, result=result, at=NOW)
        quality, coverage = planner.build_reports(
            job_id="job:financial:csi300:v1",
            dataset_version_id="dataset:financial:csi300:v1",
            result=result,
            created_at=NOW,
        )

        self.assertEqual(succeeded.status, BackfillCheckpointStatus.SUCCEEDED)
        self.assertEqual(succeeded.domain, BackfillDataDomain.FINANCIAL_STATEMENT)
        self.assertEqual(succeeded.processed_rows, 100)
        self.assertEqual(quality.status, DatasetQualityStatus.WARNED)
        self.assertEqual(coverage.expected_rows, len(unit.symbols))
        self.assertEqual(coverage.observed_rows, 1)
        self.assertEqual(coverage.coverage_ratio, 0.5)
        self.assertTrue(any("missing_security_count=1" in item for item in coverage.warnings))


if __name__ == "__main__":
    unittest.main()
