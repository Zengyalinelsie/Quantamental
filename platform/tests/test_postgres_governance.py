import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg

from a_share_platform.adapters.postgres.governance import PostgresGovernanceRepository
from a_share_platform.application.governance_ledger import GovernanceLedger
from a_share_platform.domain.governance import (
    Artifact,
    DatasetVersion,
    LineageEdge,
    RunRecord,
    RunStatus,
    VersionConflictError,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.governance import GovernanceStoreUnavailable

NOW = datetime(2026, 8, 14, 9, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def dataset(
    *,
    dataset_version_id: str = "dataset:governance:v1",
    content_hash: str = HASH_A,
) -> DatasetVersion:
    return DatasetVersion(
        dataset_version_id=dataset_version_id,
        content_hash=content_hash,
        created_at=NOW,
        schema_version="governance-test:v1",
    )


def running_run(*, run_id: str = "run:governance:001") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        run_kind="investment_view_compilation",
        status=RunStatus.RUNNING,
        context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        created_at=NOW,
        code_version="git:abc123",
        environment_fingerprint="python:3.12:test",
    )


def artifact(
    *,
    artifact_id: str = "artifact:investment-view:001",
    run_id: str = "run:governance:001",
    content_hash: str = HASH_A,
) -> Artifact:
    return Artifact(
        artifact_id=artifact_id,
        run_id=run_id,
        content_hash=content_hash,
        media_type="application/json",
        storage_uri="file:///private/artifacts/sha256/" + content_hash.removeprefix("sha256:"),
        created_at=NOW + timedelta(minutes=2),
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
        self.datasets: dict[str, tuple[object, ...]] = {}
        self.runs: dict[str, tuple[object, ...]] = {}
        self.artifacts: dict[str, tuple[object, ...]] = {}
        self.lineage: set[tuple[object, ...]] = set()
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.operational_error = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if self.operational_error:
            raise psycopg.OperationalError("database unavailable")
        normalized = " ".join(query.split())

        if normalized.startswith("INSERT INTO governance.dataset_versions"):
            if any(row[1] == params[1] and row[0] != params[0] for row in self.datasets.values()):
                raise psycopg.errors.UniqueViolation("dataset content hash conflict")
            metadata = getattr(params[4], "obj", params[4])
            self.datasets.setdefault(str(params[0]), (*params[:4], metadata))
            return FakeResult()
        if "FROM governance.dataset_versions" in normalized:
            if "WHERE dataset_version_id" in normalized:
                row = self.datasets.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            return FakeResult([self.datasets[key][:4] for key in sorted(self.datasets)])

        if normalized.startswith("INSERT INTO governance.run_records"):
            self.runs.setdefault(str(params[0]), params)
            return FakeResult()
        if normalized.startswith("UPDATE governance.run_records"):
            current = self.runs.get(str(params[3]))
            if current is not None and current[2] == params[4]:
                self.runs[str(params[3])] = (
                    current[0],
                    current[1],
                    params[0],
                    current[3],
                    current[4],
                    current[5],
                    params[1],
                    params[2],
                    current[8],
                    current[9],
                )
            return FakeResult()
        if "FROM governance.run_records" in normalized:
            if "WHERE run_id" in normalized:
                row = self.runs.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            return FakeResult([self.runs[key] for key in sorted(self.runs)])

        if normalized.startswith("INSERT INTO governance.artifacts"):
            if str(params[0]) not in self.artifacts:
                self.artifacts[str(params[0])] = params
            return FakeResult()
        if "FROM governance.artifacts" in normalized:
            if "WHERE artifact_id" in normalized:
                row = self.artifacts.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            if "WHERE content_hash" in normalized:
                row = next(
                    (value for value in self.artifacts.values() if value[1] == params[0]),
                    None,
                )
                return FakeResult([] if row is None else [row])
            return FakeResult([self.artifacts[key] for key in sorted(self.artifacts)])

        if normalized.startswith("INSERT INTO governance.lineage_edges"):
            self.lineage.add(params)
            return FakeResult()
        if "FROM governance.lineage_edges" in normalized:
            if "WHERE downstream_id" in normalized:
                return FakeResult(
                    sorted(row for row in self.lineage if row[1] == params[0])
                )
            return FakeResult(sorted(self.lineage))
        return FakeResult()


class PostgresGovernanceRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()
        self.factory_calls = 0

        @contextmanager
        def factory() -> Iterator[FakeConnection]:
            self.factory_calls += 1
            yield self.connection

        self.repository = PostgresGovernanceRepository(factory)

    def test_round_trip_uses_layered_tables_and_preserves_complete_contracts(self) -> None:
        run = running_run()
        self.assertEqual(self.repository.register_dataset(dataset()), dataset())
        self.assertEqual(self.repository.register_run(run), run)
        self.assertEqual(self.repository.get_run(run.run_id), run)
        self.assertEqual(self.repository.register_artifact(artifact()), artifact())
        edge = LineageEdge(run.run_id, artifact().artifact_id, "produced")
        self.assertEqual(self.repository.register_lineage(edge), edge)

        self.assertEqual(self.repository.list_datasets(), (dataset(),))
        self.assertEqual(self.repository.list_runs(), (run,))
        self.assertEqual(self.repository.get_artifact(artifact().artifact_id), artifact())
        self.assertEqual(self.repository.list_artifacts(), (artifact(),))
        self.assertEqual(self.repository.list_lineage(), (edge,))
        sql = "\n".join(query for query, _ in self.connection.calls)
        for table in ("dataset_versions", "run_records", "artifacts", "lineage_edges"):
            self.assertIn(f"governance.{table}", sql)
        self.assertIn("SET TRANSACTION READ ONLY", sql)

    def test_run_registration_is_idempotent_and_conflicts_fail_closed(self) -> None:
        run = running_run()
        self.assertEqual(self.repository.register_run(run), run)
        self.assertEqual(self.repository.register_run(run), run)
        with self.assertRaisesRegex(VersionConflictError, run.run_id):
            self.repository.register_run(replace(run, run_kind="different"))

    def test_dataset_content_hash_unique_violation_is_a_domain_conflict(self) -> None:
        self.repository.register_dataset(dataset())
        with self.assertRaisesRegex(VersionConflictError, "dataset:governance:other"):
            self.repository.register_dataset(
                dataset(dataset_version_id="dataset:governance:other")
            )

    def test_ledger_can_persist_one_terminal_transition_without_losing_context(self) -> None:
        ledger = GovernanceLedger(self.repository)
        run = ledger.register_run(running_run())
        finished = ledger.finish_run(
            run.run_id,
            status=RunStatus.SUCCEEDED,
            finished_at=NOW + timedelta(minutes=1),
        )
        self.assertEqual(finished.status, RunStatus.SUCCEEDED)
        self.assertEqual(finished.context, run.context)
        self.assertEqual(self.repository.get_run(run.run_id), finished)

    def test_repository_accepts_pending_to_running_transition(self) -> None:
        pending = replace(running_run(), status=RunStatus.PENDING)
        self.repository.register_run(pending)
        running = replace(pending, status=RunStatus.RUNNING)
        self.assertEqual(self.repository.append_run_state(running), running)

    def test_artifact_requires_run_and_id_and_hash_are_immutable(self) -> None:
        with self.assertRaisesRegex(ValueError, "run does not exist"):
            self.repository.register_artifact(artifact())
        self.repository.register_run(running_run())
        value = self.repository.register_artifact(artifact())
        self.assertEqual(self.repository.register_artifact(value), value)
        with self.assertRaisesRegex(VersionConflictError, value.artifact_id):
            self.repository.register_artifact(
                artifact(content_hash=HASH_B)
            )
        with self.assertRaisesRegex(VersionConflictError, HASH_A):
            self.repository.register_artifact(
                artifact(artifact_id="artifact:investment-view:other")
            )

    def test_lineage_is_idempotent(self) -> None:
        edge = LineageEdge("view:001", "artifact:001", "frozen_as")
        self.assertEqual(self.repository.register_lineage(edge), edge)
        self.assertEqual(self.repository.register_lineage(edge), edge)
        self.assertEqual(self.repository.list_lineage(), (edge,))

    def test_artifact_and_lineage_batch_is_one_transaction_with_exact_queries(self) -> None:
        self.repository.register_run(running_run())
        value = artifact()
        edges = (
            LineageEdge(value.run_id, value.artifact_id, "produced"),
            LineageEdge("view:001", value.artifact_id, "frozen_as"),
        )
        before = self.factory_calls
        stored = self.repository.register_artifact_with_lineage(value, edges)
        self.assertEqual(self.factory_calls - before, 1)
        self.assertEqual(stored, value)
        self.assertEqual(self.repository.get_artifact_by_hash(value.content_hash), value)
        self.assertEqual(
            self.repository.list_lineage_for(value.artifact_id),
            tuple(sorted(edges, key=lambda edge: (edge.upstream_id, edge.relation))),
        )

    def test_operational_errors_are_explicitly_unavailable(self) -> None:
        self.connection.operational_error = True
        with self.assertRaisesRegex(GovernanceStoreUnavailable, "governance store"):
            self.repository.list_artifacts()


if __name__ == "__main__":
    unittest.main()
