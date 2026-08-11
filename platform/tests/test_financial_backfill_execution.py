import unittest
from dataclasses import replace
from datetime import UTC, date, datetime

from a_share_platform.application.financial_backfill import (
    FinancialBackfillPlanner,
    FinancialBackfillRunOutcome,
)
from a_share_platform.application.financial_backfill_execution import (
    FinancialBackfillExecutionService,
)
from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.domain.backfill import BackfillCheckpointStatus, BackfillJobStatus
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
        plan_id="financial-backfill:csi300:akshare-pilot:v1",
        provider_id="akshare",
        provider_profile_version="financial-source:akshare:v1",
        cohort=FinancialBackfillCohort.CSI_300,
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="metric-mapping:akshare-eastmoney:v1",
        statements=(
            FinancialStatementSelection(StatementType.BALANCE_SHEET, "balance_sheet"),
        ),
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
        warnings=("private local current research only",),
    )


class StubJobCoordinator:
    def __init__(self, initial_status: BackfillJobStatus = BackfillJobStatus.RUNNING) -> None:
        preview = FinancialBackfillPlanner().preview(plan(), profile())
        initial = FinancialBackfillJobRecord.initial(preview)
        self.job = replace(
            initial,
            status=initial_status,
            dataset_version_id=(
                "dataset:financial:aggregate:v1"
                if initial_status is BackfillJobStatus.SUCCEEDED
                else None
            ),
        )
        self.bootstrap_calls = 0
        self.finalize_calls = 0
        self.fail_reasons: list[str] = []

    def bootstrap(self, _preview):  # type: ignore[no-untyped-def]
        self.bootstrap_calls += 1
        return self.job

    def finalize(self, _preview):  # type: ignore[no-untyped-def]
        self.finalize_calls += 1
        self.job = self.job.transition(
            BackfillJobStatus.SUCCEEDED,
            at=NOW,
            dataset_version_id="dataset:financial:aggregate:v1",
        )
        return self.job

    def fail(self, _preview, reason: str):  # type: ignore[no-untyped-def]
        self.fail_reasons.append(reason)
        self.job = self.job.transition(
            BackfillJobStatus.FAILED,
            at=NOW,
            failure_reasons=(reason,),
        )
        return self.job


class StubRunner:
    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls = []
        self.fail_on_call = fail_on_call

    def run_unit(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if len(self.calls) == self.fail_on_call:
            raise TimeoutError("provider timeout")
        unit = kwargs["work_unit"]
        checkpoint = FinancialBackfillPlanner.pending_checkpoint(
            job_id=kwargs["job_id"],
            unit=unit,
            at=NOW,
        ).transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        checkpoint = checkpoint.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=NOW,
            processed_rows=1,
            rejected_rows=0,
            content_hash="sha256:" + "a" * 64,
            retrieval_metadata=None,
        )
        return FinancialBackfillRunOutcome(
            checkpoint=checkpoint,
            dataset_version_id=f"dataset:{len(self.calls)}",
            observation_ids=(f"observation:{len(self.calls)}",),
            skipped=len(self.calls) == 1,
        )


class StubSource:
    provider_id = "akshare"


class FinancialBackfillExecutionServiceTest(unittest.TestCase):
    def test_runs_every_work_unit_then_finalizes_one_aggregate(self) -> None:
        coordinator = StubJobCoordinator()
        runner = StubRunner()
        service = FinancialBackfillExecutionService(
            planner=FinancialBackfillPlanner(),
            job_coordinator=coordinator,
            runner=runner,
        )

        result = service.run(plan=plan(), profile=profile(), source=StubSource())

        self.assertEqual(result.status, BackfillJobStatus.SUCCEEDED)
        self.assertTrue(result.writes_performed)
        self.assertEqual(result.completed_work_units, 2)
        self.assertEqual(result.skipped_work_units, 1)
        self.assertEqual(result.aggregate_dataset_version_id, "dataset:financial:aggregate:v1")
        self.assertEqual(result.unit_dataset_version_ids, ("dataset:1", "dataset:2"))
        self.assertEqual(len(runner.calls), 2)
        self.assertEqual(coordinator.finalize_calls, 1)

    def test_failure_is_audited_and_aggregate_is_not_finalized(self) -> None:
        coordinator = StubJobCoordinator()
        runner = StubRunner(fail_on_call=2)
        service = FinancialBackfillExecutionService(
            planner=FinancialBackfillPlanner(),
            job_coordinator=coordinator,
            runner=runner,
        )

        with self.assertRaisesRegex(TimeoutError, "provider timeout"):
            service.run(plan=plan(), profile=profile(), source=StubSource())

        self.assertEqual(coordinator.finalize_calls, 0)
        self.assertEqual(coordinator.fail_reasons, ["TimeoutError: provider timeout"])

    def test_succeeded_job_is_idempotent_without_reopening_work_units(self) -> None:
        coordinator = StubJobCoordinator(BackfillJobStatus.SUCCEEDED)
        runner = StubRunner()
        service = FinancialBackfillExecutionService(
            planner=FinancialBackfillPlanner(),
            job_coordinator=coordinator,
            runner=runner,
        )

        result = service.run(plan=plan(), profile=profile(), source=StubSource())

        self.assertEqual(result.status, BackfillJobStatus.SUCCEEDED)
        self.assertFalse(result.writes_performed)
        self.assertEqual(result.completed_work_units, 2)
        self.assertEqual(result.skipped_work_units, 2)
        self.assertEqual(runner.calls, [])
        self.assertEqual(coordinator.finalize_calls, 0)


if __name__ == "__main__":
    unittest.main()
