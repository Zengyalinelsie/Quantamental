import unittest
from datetime import UTC, date, datetime

from a_share_platform.adapters.memory.backfill import InMemoryBackfillRepository
from a_share_platform.application.backfill import (
    BackfillPlanner,
    BackfillService,
    build_csi_backfill_plan,
)
from a_share_platform.application.provider_registry import build_p2_provider_registry
from a_share_platform.domain.backfill import (
    BackfillDataDomain,
    BackfillJobStatus,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


class RecordingSource:
    def __init__(self) -> None:
        self.calls = 0

    def fetch(self, *_args: object, **_kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("a blocked provider must never be called")


class BackfillServiceTest(unittest.TestCase):
    def test_default_plan_has_full_master_and_both_index_histories_from_2018(self) -> None:
        value = build_csi_backfill_plan(
            plan_id="plan:v1",
            provider_id="a_share_mcp_baostock",
            end_date=date(2026, 8, 8),
            created_at=NOW,
        )
        self.assertEqual(value.start_date, date(2018, 1, 1))
        self.assertEqual(
            tuple(scope.scope_id for scope in value.scopes),
            ("a-share:security-master", "index:000300", "index:000905"),
        )
        self.assertEqual(
            set(value.domains),
            {
                BackfillDataDomain.SECURITY_MASTER,
                BackfillDataDomain.UNIVERSE,
                BackfillDataDomain.RAW_DAILY_BAR,
                BackfillDataDomain.SHARE_CAPITAL,
                BackfillDataDomain.CORPORATE_ACTION,
                BackfillDataDomain.TRADING_CALENDAR,
            },
        )

    def test_work_units_are_deterministic_year_chunks_with_no_duplicate_keys(self) -> None:
        value = build_csi_backfill_plan(
            plan_id="plan:v1",
            provider_id="a_share_mcp_baostock",
            start_date=date(2018, 1, 1),
            end_date=date(2019, 2, 1),
            created_at=NOW,
        )
        first = BackfillPlanner().work_units(value)
        second = BackfillPlanner().work_units(value)
        self.assertEqual(first, second)
        self.assertEqual(len({unit.checkpoint_key for unit in first}), len(first))
        self.assertTrue(
            any(
                unit.scope_id == "index:000300"
                and unit.domain is BackfillDataDomain.RAW_DAILY_BAR
                and unit.start_date == date(2018, 1, 1)
                and unit.end_date == date(2018, 12, 31)
                for unit in first
            )
        )
        self.assertFalse(
            any(
                unit.scope_id == "a-share:security-master"
                and unit.domain is BackfillDataDomain.RAW_DAILY_BAR
                for unit in first
            )
        )

    def test_free_sources_block_execution_before_network_or_storage(self) -> None:
        repository = InMemoryBackfillRepository()
        source = RecordingSource()
        value = build_csi_backfill_plan(
            plan_id="plan:blocked:v1",
            provider_id="a_share_mcp_baostock",
            end_date=date(2026, 8, 8),
            created_at=NOW,
        )
        service = BackfillService(
            registry=build_p2_provider_registry(),
            repository=repository,
            clock=lambda: NOW,
        )

        preview = service.preview(value)
        self.assertFalse(preview.qualification.permitted)
        self.assertTrue(
            any("raw_bulk_persistence" in reason for reason in preview.qualification.blockers)
        )
        job = service.start(value, source=source, sink=None)
        self.assertEqual(job.status, BackfillJobStatus.BLOCKED)
        self.assertEqual(source.calls, 0)
        self.assertEqual(repository.get_job(job.job_id), job)
        self.assertEqual(repository.list_checkpoints(job.job_id), ())

    def test_dry_run_is_read_only(self) -> None:
        repository = InMemoryBackfillRepository()
        value = build_csi_backfill_plan(
            plan_id="plan:dry:v1",
            provider_id="futu_quote",
            end_date=date(2026, 8, 8),
            created_at=NOW,
        )
        service = BackfillService(
            registry=build_p2_provider_registry(),
            repository=repository,
            clock=lambda: NOW,
        )
        preview = service.preview(value)
        self.assertFalse(preview.qualification.permitted)
        self.assertEqual(repository.list_jobs(), ())


if __name__ == "__main__":
    unittest.main()
