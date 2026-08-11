import json
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import cast

from a_share_platform.adapters.postgres.financial_backfill_job import (
    PostgresFinancialBackfillJobRepository,
)
from a_share_platform.application.financial_backfill import FinancialBackfillPlanner
from a_share_platform.application.financial_backfill_job import (
    FinancialBackfillFinalizationError,
    FinancialBackfillJobCoordinator,
    FinancialBackfillJobRecord,
    FinancialCompletedWorkUnit,
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
from a_share_platform.domain.governance import DatasetVersion, VersionConflictError
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

NOW = datetime(2026, 8, 11, 3, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def plan() -> FinancialBackfillPlan:
    return FinancialBackfillPlan(
        plan_id="financial-backfill:csi300:2019-2020:v1",
        provider_id="akshare",
        provider_profile_version="financial-source:akshare:v1",
        cohort=FinancialBackfillCohort.CSI_300,
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="mapping:akshare:v1",
        statements=(
            FinancialStatementSelection(
                StatementType.BALANCE_SHEET,
                "balance_sheet",
            ),
        ),
        report_period_ends=(date(2019, 12, 31), date(2020, 12, 31)),
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


def preview():  # type: ignore[no-untyped-def]
    return FinancialBackfillPlanner().preview(plan(), profile())


def completed_units() -> tuple[FinancialCompletedWorkUnit, ...]:
    units = preview().work_units
    return tuple(
        FinancialCompletedWorkUnit(
            checkpoint_key=unit.checkpoint_key,
            dataset_version_id=f"dataset:financial-unit:{index}:v1",
            content_hash=HASH_A if index == 1 else HASH_B,
            observation_count=index,
            completed_at=NOW + timedelta(minutes=index),
        )
        for index, unit in enumerate(units, start=1)
    )


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class InMemoryFinancialJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, FinancialBackfillJobRecord] = {}
        self.events: list[FinancialBackfillJobRecord] = []
        self.completed: tuple[FinancialCompletedWorkUnit, ...] = ()
        self.datasets: dict[str, tuple[DatasetVersion, dict[str, object]]] = {}
        self.commits = 0
        self.rollbacks = 0

    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None:
        return self.jobs.get(job_id)

    def create_job(self, value: FinancialBackfillJobRecord) -> FinancialBackfillJobRecord:
        for existing in self.jobs.values():
            if existing.job_id == value.job_id or existing.plan.plan_id == value.plan.plan_id:
                if existing != value:
                    raise VersionConflictError("immutable financial job conflict")
                return existing
        self.jobs[value.job_id] = value
        self.events.append(value)
        return value

    def append_job_state(
        self,
        value: FinancialBackfillJobRecord,
        *,
        expected_previous_status: BackfillJobStatus,
    ) -> FinancialBackfillJobRecord:
        existing = self.jobs[value.job_id]
        if existing.status is not expected_previous_status:
            if existing == value:
                return existing
            raise VersionConflictError("financial job transition conflict")
        self.jobs[value.job_id] = value
        self.events.append(value)
        return value

    def list_completed_units(self, _job_id: str) -> tuple[FinancialCompletedWorkUnit, ...]:
        return self.completed

    def register_aggregate_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: dict[str, object],
    ) -> DatasetVersion:
        existing = self.datasets.get(value.dataset_version_id)
        candidate = (value, metadata)
        if existing is not None and existing != candidate:
            raise VersionConflictError("aggregate dataset conflict")
        self.datasets[value.dataset_version_id] = candidate
        return value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FinancialBackfillJobCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryFinancialJobRepository()
        self.clock = MutableClock(NOW)
        self.coordinator = FinancialBackfillJobCoordinator(
            repository=self.repository,
            clock=self.clock,
        )

    def test_bootstrap_and_aggregate_finalization_are_auditable_and_idempotent(self) -> None:
        value = preview()
        running = self.coordinator.bootstrap(value)
        self.assertEqual(running.status, BackfillJobStatus.RUNNING)
        self.assertEqual(
            [event.status for event in self.repository.events],
            [BackfillJobStatus.PLANNED, BackfillJobStatus.RUNNING],
        )
        self.repository.completed = completed_units()

        succeeded = self.coordinator.finalize(value)
        repeated = self.coordinator.finalize(value)

        self.assertEqual(succeeded, repeated)
        self.assertEqual(succeeded.status, BackfillJobStatus.SUCCEEDED)
        self.assertIsNotNone(succeeded.dataset_version_id)
        self.assertEqual(
            [event.status for event in self.repository.events],
            [
                BackfillJobStatus.PLANNED,
                BackfillJobStatus.RUNNING,
                BackfillJobStatus.SUCCEEDED,
            ],
        )
        self.assertEqual(len(self.repository.datasets), 1)
        dataset, metadata = next(iter(self.repository.datasets.values()))
        manifest = cast(dict[str, object], metadata["manifest"])
        self.assertEqual(dataset.created_at, NOW + timedelta(minutes=2))
        self.assertEqual(manifest["trust_state"], "normalized_current")
        self.assertEqual(manifest["data_mode"], "current_research")
        self.assertEqual(manifest["adjustment_mode"], "not_applicable")
        self.assertFalse(manifest["pit_verified"])
        entries = cast(list[dict[str, object]], manifest["units"])
        self.assertEqual(
            [entry["checkpoint_key"] for entry in entries],
            [unit.checkpoint_key for unit in value.work_units],
        )
        self.assertEqual(
            [entry["dataset_version_id"] for entry in entries],
            [unit.dataset_version_id for unit in completed_units()],
        )

    def test_incomplete_finalization_is_failed_audited_then_resumable(self) -> None:
        value = preview()
        self.coordinator.bootstrap(value)
        self.repository.completed = completed_units()[:1]

        with self.assertRaisesRegex(
            FinancialBackfillFinalizationError,
            "completed checkpoint set",
        ):
            self.coordinator.finalize(value)

        failed = self.repository.get_job(f"job:{value.plan.plan_id}")
        self.assertEqual(failed.status, BackfillJobStatus.FAILED)  # type: ignore[union-attr]
        self.assertTrue(failed.failure_reasons)  # type: ignore[union-attr]
        self.assertEqual(self.repository.rollbacks, 1)

        self.clock.advance(1)
        resumed = self.coordinator.bootstrap(value)
        self.repository.completed = completed_units()
        succeeded = self.coordinator.finalize(value)

        self.assertEqual(resumed.status, BackfillJobStatus.RUNNING)
        self.assertEqual(succeeded.status, BackfillJobStatus.SUCCEEDED)
        self.assertEqual(
            [event.status for event in self.repository.events],
            [
                BackfillJobStatus.PLANNED,
                BackfillJobStatus.RUNNING,
                BackfillJobStatus.FAILED,
                BackfillJobStatus.RUNNING,
                BackfillJobStatus.SUCCEEDED,
            ],
        )

    def test_existing_job_with_different_plan_or_qualification_fails_closed(self) -> None:
        value = preview()
        self.coordinator.bootstrap(value)
        changed_plan = replace(value.plan, symbols=("SH.600001",))
        changed_preview = replace(value, plan=changed_plan)
        changed_qualification = replace(
            value,
            qualification=replace(
                value.qualification,
                warnings=(*value.qualification.warnings, "different"),
            ),
        )

        for conflict in (changed_preview, changed_qualification):
            with self.subTest(conflict=conflict), self.assertRaises(VersionConflictError):
                self.coordinator.bootstrap(conflict)


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class SequenceConnection:
    def __init__(self, responses: list[list[tuple[object, ...]]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        rows = [] if not self.responses else self.responses.pop(0)
        return FakeResult(rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    wrapped = getattr(value, "obj", None)
    return value if wrapped is None else wrapped


def job_row(value: FinancialBackfillJobRecord) -> tuple[object, ...]:
    repository = PostgresFinancialBackfillJobRepository
    return (
        value.job_id,
        value.plan.plan_id,
        repository.plan_json(value.plan),
        repository.qualification_json(value.qualification),
        value.status.value,
        value.created_at,
        value.updated_at,
        value.dataset_version_id,
        list(value.failure_reasons),
        value.plan.provider_id,
        value.plan.output_trust_state.value,
        "not_applicable",
        min(value.plan.report_period_ends),
        max(value.plan.report_period_ends),
    )


class PostgresFinancialBackfillJobRepositoryTest(unittest.TestCase):
    def test_create_persists_immutable_financial_json_and_initial_event(self) -> None:
        value = FinancialBackfillJobRecord.initial(preview())
        connection = SequenceConnection([[], [job_row(value)]])
        repository = PostgresFinancialBackfillJobRepository(connection)

        restored = repository.create_job(value)

        self.assertEqual(restored, value)
        query, params = connection.calls[0]
        self.assertIn("INSERT INTO ingestion_jobs", query)
        self.assertIn("INSERT INTO ingestion_job_events", query)
        self.assertEqual(params[7], "not_applicable")
        self.assertEqual(json_value(params[4]), repository.plan_json(value.plan))
        self.assertEqual(
            json_value(params[5]),
            repository.qualification_json(value.qualification),
        )

    def test_same_plan_bound_to_another_job_id_is_an_immutable_conflict(self) -> None:
        value = FinancialBackfillJobRecord.initial(preview())
        conflicting_row = list(job_row(value))
        conflicting_row[0] = "job:other-financial-plan"
        connection = SequenceConnection([[], [tuple(conflicting_row)]])
        repository = PostgresFinancialBackfillJobRepository(connection)

        with self.assertRaises(VersionConflictError):
            repository.create_job(value)

    def test_completed_unit_query_binds_checkpoint_receipt_hash_count_and_time(self) -> None:
        expected = completed_units()[0]
        connection = SequenceConnection(
            [
                [
                    (
                        expected.checkpoint_key,
                        expected.dataset_version_id,
                        expected.content_hash,
                        expected.observation_count,
                        expected.completed_at,
                    )
                ]
            ]
        )
        repository = PostgresFinancialBackfillJobRepository(connection)

        restored = repository.list_completed_units("job:financial:test")

        self.assertEqual(restored, (expected,))
        query, _params = connection.calls[0]
        self.assertIn("financial_backfill_persist_receipts", query)
        self.assertIn("status = 'succeeded'", query)


if __name__ == "__main__":
    unittest.main()
