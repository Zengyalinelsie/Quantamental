import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime

from a_share_platform.adapters.postgres.experiments import (
    PostgresExperimentRunRepository,
)
from a_share_platform.domain.experiments import (
    ExperimentFailure,
    ExperimentRun,
    ExperimentRunConflict,
    ExperimentRunStatus,
)
from tests.test_experiment_application import succeeded_run
from tests.test_experiments import artifact, metric, spec


def json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "obj"):
        return value.obj
    return value


def failed_run() -> ExperimentRun:
    return ExperimentRun(
        run_id="experiment-run:quality-csi300:failed-001",
        spec=spec(),
        status=ExperimentRunStatus.FAILED,
        started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
        finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
        metrics=(metric("rank_ic", "0.005"),),
        artifacts=(artifact("f"),),
        failure=ExperimentFailure(
            stage="metric-evaluation",
            error_type="CoverageGateError",
            message="coverage 0.62 is below 0.80",
            occurred_at=datetime(2026, 8, 11, 1, 30, tzinfo=UTC),
            retryable=False,
        ),
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.spec_rows: dict[str, tuple[object, ...]] = {}
        self.run_rows: dict[str, tuple[object, ...]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        normalized = " ".join(query.split())
        if normalized.startswith("INSERT INTO research.experiment_specs"):
            spec_id = str(params[0])
            self.spec_rows.setdefault(spec_id, params)
            return FakeResult()
        if normalized.startswith("INSERT INTO research.experiment_runs"):
            run_id = str(params[0])
            self.run_rows.setdefault(run_id, params)
            return FakeResult()
        if "FROM research.experiment_specs" in normalized:
            row = self.spec_rows.get(str(params[0]))
            return FakeResult([] if row is None else [row])
        if "FROM research.experiment_runs" in normalized and "WHERE run_id" in normalized:
            row = self.run_rows.get(str(params[0]))
            return FakeResult([] if row is None else [row])
        if "FROM research.experiment_runs" in normalized:
            return FakeResult([self.run_rows[key] for key in sorted(self.run_rows)])
        return FakeResult()


class PostgresExperimentRunRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()

        @contextmanager
        def factory() -> Iterator[FakeConnection]:
            yield self.connection

        self.repository = PostgresExperimentRunRepository(factory)

    def test_save_is_append_only_and_round_trips_complete_reproducibility_binding(self) -> None:
        value = succeeded_run()

        self.assertEqual(self.repository.save_run(value), value)
        self.assertEqual(self.repository.get_run(value.run_id), value)

        spec_query, spec_params = next(
            call for call in self.connection.calls if "INSERT INTO research.experiment_specs" in call[0]
        )
        run_query, run_params = next(
            call for call in self.connection.calls if "INSERT INTO research.experiment_runs" in call[0]
        )
        self.assertIn("ON CONFLICT (spec_id) DO NOTHING", spec_query)
        self.assertIn("ON CONFLICT (run_id) DO NOTHING", run_query)
        self.assertFalse(any("UPDATE" in query for query, _ in self.connection.calls))
        self.assertEqual(spec_params[1], value.spec.content_hash)
        self.assertEqual(run_params[2], value.spec_hash)
        self.assertEqual(json_value(spec_params[-1])["code_sha"], value.spec.code_sha)
        self.assertEqual(json_value(run_params[6])[0]["value"], "0.031")

    def test_failed_run_is_listed_with_failure_evidence_and_partial_outputs(self) -> None:
        value = failed_run()

        self.repository.save_run(value)

        self.assertEqual(self.repository.list_runs(), (value,))
        restored = self.repository.get_run(value.run_id)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.failure, value.failure)  # type: ignore[union-attr]
        self.assertEqual(restored.metrics, value.metrics)  # type: ignore[union-attr]

    def test_reusing_run_or_spec_identifier_with_different_content_fails_closed(self) -> None:
        value = succeeded_run()
        self.repository.save_run(value)

        with self.assertRaisesRegex(ExperimentRunConflict, "experiment run"):
            self.repository.save_run(replace(value, artifacts=(artifact("a"),)))

        conflicting_spec = replace(value.spec, research_question="A different question")
        conflicting_run = replace(
            value,
            run_id="experiment-run:quality-csi300:002",
            spec=conflicting_spec,
        )
        with self.assertRaisesRegex(ExperimentRunConflict, "experiment spec"):
            self.repository.save_run(conflicting_run)


if __name__ == "__main__":
    unittest.main()
