import unittest
from dataclasses import replace
from datetime import UTC, datetime

from a_share_platform.adapters.memory.experiments import (
    InMemoryExperimentRunRepository,
    UnavailableExperimentRunRepository,
)
from a_share_platform.application.experiments import ExperimentRunService
from a_share_platform.domain.experiments import (
    ExperimentRun,
    ExperimentRunConflict,
    ExperimentRunStatus,
)
from a_share_platform.ports.experiments import ExperimentStoreUnavailable
from tests.test_experiments import artifact, metric, spec


def succeeded_run() -> ExperimentRun:
    return ExperimentRun(
        run_id="experiment-run:quality-csi300:001",
        spec=spec(),
        status=ExperimentRunStatus.SUCCEEDED,
        started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
        finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
        metrics=(metric("rank_ic", "0.031"), metric("turnover", "0.12")),
        artifacts=(artifact(),),
        failure=None,
    )


class ExperimentRunServiceTest(unittest.TestCase):
    def test_create_read_and_list_are_idempotent_and_immutable(self) -> None:
        repository = InMemoryExperimentRunRepository()
        service = ExperimentRunService(repository)
        value = succeeded_run()

        self.assertEqual(service.create_run(value), value)
        self.assertEqual(service.create_run(value), value)
        self.assertEqual(service.get_run(value.run_id), value)
        self.assertEqual(service.list_runs(), (value,))

        with self.assertRaises(ExperimentRunConflict):
            service.create_run(replace(value, artifacts=(artifact("a"),)))

    def test_missing_store_is_explicitly_unavailable_not_an_empty_collection(self) -> None:
        service = ExperimentRunService(
            UnavailableExperimentRunRepository(
                "ASP_DATABASE_URL is not configured for experiment persistence"
            )
        )

        with self.assertRaisesRegex(ExperimentStoreUnavailable, "ASP_DATABASE_URL"):
            service.list_runs()
        with self.assertRaises(ExperimentStoreUnavailable):
            service.get_run("experiment-run:missing")
        with self.assertRaises(ExperimentStoreUnavailable):
            service.create_run(succeeded_run())


if __name__ == "__main__":
    unittest.main()
