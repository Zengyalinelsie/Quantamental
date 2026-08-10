import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.application.governance_ledger import GovernanceLedger
from a_share_platform.domain.governance import (
    Artifact,
    DatasetVersion,
    InvalidRunTransitionError,
    LineageEdge,
    RunRecord,
    RunStatus,
    VersionConflictError,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

NOW = datetime(2026, 8, 10, 9, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def dataset(*, content_hash: str = HASH_A) -> DatasetVersion:
    return DatasetVersion(
        dataset_version_id="dataset:prices:v1",
        content_hash=content_hash,
        created_at=NOW,
        schema_version="prices:v1",
    )


def running_run() -> RunRecord:
    return RunRecord(
        run_id="run:001",
        run_kind="dataset_ingestion",
        status=RunStatus.RUNNING,
        context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        created_at=NOW,
        code_version="git:abc123",
        environment_fingerprint="python:3.12:test",
    )


class GovernanceLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryGovernanceRepository()
        self.ledger = GovernanceLedger(self.repository)

    def test_duplicate_dataset_write_is_idempotent(self) -> None:
        first = self.ledger.register_dataset(dataset())
        second = self.ledger.register_dataset(dataset())
        self.assertIs(first, second)
        self.assertEqual(self.repository.list_datasets(), (first,))

    def test_dataset_id_cannot_be_overwritten_with_a_new_hash(self) -> None:
        self.ledger.register_dataset(dataset())
        with self.assertRaisesRegex(VersionConflictError, "dataset:prices:v1"):
            self.ledger.register_dataset(dataset(content_hash=HASH_B))

    def test_dataset_versions_are_frozen(self) -> None:
        value = dataset()
        with self.assertRaises(FrozenInstanceError):
            value.content_hash = HASH_B  # type: ignore[misc]

    def test_failed_run_is_retained_with_reason_and_history(self) -> None:
        self.ledger.register_run(running_run())
        failed = self.ledger.finish_run(
            "run:001",
            status=RunStatus.FAILED,
            finished_at=NOW + timedelta(minutes=2),
            failure_reason="provider timeout",
        )
        self.assertEqual(failed.failure_reason, "provider timeout")
        self.assertEqual(
            tuple(item.status for item in self.repository.run_history("run:001")),
            (RunStatus.RUNNING, RunStatus.FAILED),
        )

    def test_terminal_run_cannot_transition_again(self) -> None:
        self.ledger.register_run(running_run())
        self.ledger.finish_run(
            "run:001",
            status=RunStatus.SUCCEEDED,
            finished_at=NOW + timedelta(minutes=1),
        )
        with self.assertRaises(InvalidRunTransitionError):
            self.ledger.finish_run(
                "run:001",
                status=RunStatus.FAILED,
                finished_at=NOW + timedelta(minutes=2),
                failure_reason="late failure",
            )

    def test_artifact_write_is_idempotent_and_hash_bound(self) -> None:
        self.ledger.register_run(running_run())
        artifact = Artifact(
            artifact_id="artifact:001",
            run_id="run:001",
            content_hash=HASH_A,
            media_type="application/json",
            storage_uri="s3://a-share-platform-test/runs/001/result.json",
            created_at=NOW,
        )
        self.assertIs(self.ledger.register_artifact(artifact), artifact)
        self.assertIs(self.ledger.register_artifact(artifact), artifact)
        with self.assertRaises(VersionConflictError):
            self.ledger.register_artifact(
                Artifact(
                    artifact_id="artifact:001",
                    run_id="run:001",
                    content_hash=HASH_B,
                    media_type=artifact.media_type,
                    storage_uri=artifact.storage_uri,
                    created_at=artifact.created_at,
                )
            )

    def test_lineage_edges_are_idempotent_and_cannot_reference_self(self) -> None:
        edge = LineageEdge("dataset:prices:v1", "run:001", "consumed_by")
        self.assertIs(self.ledger.register_lineage(edge), edge)
        self.assertIs(self.ledger.register_lineage(edge), edge)
        self.assertEqual(self.repository.list_lineage(), (edge,))
        with self.assertRaisesRegex(ValueError, "must differ"):
            LineageEdge("run:001", "run:001", "derived_from")


if __name__ == "__main__":
    unittest.main()
