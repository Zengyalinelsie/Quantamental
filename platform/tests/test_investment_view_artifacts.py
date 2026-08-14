import hashlib
import json
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.adapters.object_store.local import LocalRawObjectStore
from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerService,
)
from a_share_platform.application.governance_ledger import GovernanceLedger
from a_share_platform.application.investment_view_artifacts import (
    InvestmentViewArtifactExporter,
)
from a_share_platform.domain.expected_return import ExpectedReturnCompilerV0
from a_share_platform.domain.governance import (
    Artifact,
    RunRecord,
    RunStatus,
    VersionConflictError,
)
from tests.test_expected_return_compiler import DECISION_TIME, request


def succeeded_run():  # type: ignore[no-untyped-def]
    value = request()
    return RunRecord(
        run_id=value.run_id,
        run_kind="investment_view_compilation",
        status=RunStatus.SUCCEEDED,
        context=value.run_context,
        created_at=DECISION_TIME,
        code_version=value.code_version,
        environment_fingerprint=value.environment_id,
        finished_at=DECISION_TIME + timedelta(minutes=1),
    )


class InvestmentViewArtifactExporterTest(unittest.TestCase):
    def test_concurrent_equivalent_registration_recovers_idempotently(self) -> None:
        class RacingRepository(InMemoryGovernanceRepository):
            raced = False

            def register_artifact_with_lineage(self, value, lineage):  # type: ignore[no-untyped-def]
                if not self.raced:
                    self.raced = True
                    winner = replace(
                        value,
                        created_at=value.created_at - timedelta(seconds=1),
                    )
                    super().register_artifact_with_lineage(winner, lineage)
                    raise VersionConflictError("simulated concurrent winner")
                return super().register_artifact_with_lineage(value, lineage)

        expected = InMemoryExpectedReturnLedgerRepository()
        governance = RacingRepository()
        view = ExpectedReturnCompilerV0().compile(request())
        ExpectedReturnLedgerService(expected).record_view(view)
        GovernanceLedger(governance).register_run(succeeded_run())
        with TemporaryDirectory() as directory:
            result = InvestmentViewArtifactExporter(
                ExpectedReturnLedgerService(expected),
                GovernanceLedger(governance),
                LocalRawObjectStore(Path(directory)),
            ).export(
                view.view_id,
                created_at=DECISION_TIME + timedelta(minutes=2),
            )
        self.assertFalse(result.writes_performed)
        self.assertEqual(
            result.artifact.created_at,
            DECISION_TIME + timedelta(minutes=2) - timedelta(seconds=1),
        )

    def test_export_uses_exact_governance_lookups_not_full_ledger_scans(self) -> None:
        class ExactLookupRepository(InMemoryGovernanceRepository):
            def list_artifacts(self):  # type: ignore[no-untyped-def]
                raise AssertionError("export must not scan all Artifacts")

            def list_lineage(self):  # type: ignore[no-untyped-def]
                raise AssertionError("export must not scan all lineage")

        expected = InMemoryExpectedReturnLedgerRepository()
        governance = ExactLookupRepository()
        view = ExpectedReturnCompilerV0().compile(request())
        ExpectedReturnLedgerService(expected).record_view(view)
        GovernanceLedger(governance).register_run(succeeded_run())
        with TemporaryDirectory() as directory:
            exporter = InvestmentViewArtifactExporter(
                ExpectedReturnLedgerService(expected),
                GovernanceLedger(governance),
                LocalRawObjectStore(Path(directory)),
            )
            first = exporter.export(
                view.view_id,
                created_at=DECISION_TIME + timedelta(minutes=2),
            )
            second = exporter.export(
                view.view_id,
                created_at=DECISION_TIME + timedelta(minutes=3),
            )
        self.assertTrue(first.writes_performed)
        self.assertFalse(second.writes_performed)

    def test_exports_canonical_content_addressed_json_and_complete_lineage(self) -> None:
        expected = InMemoryExpectedReturnLedgerRepository()
        governance = InMemoryGovernanceRepository()
        view = ExpectedReturnCompilerV0().compile(request())
        ExpectedReturnLedgerService(expected).record_view(view)
        GovernanceLedger(governance).register_run(succeeded_run())

        with TemporaryDirectory() as directory:
            exporter = InvestmentViewArtifactExporter(
                ExpectedReturnLedgerService(expected),
                GovernanceLedger(governance),
                LocalRawObjectStore(Path(directory)),
            )
            first = exporter.export(
                view.view_id,
                created_at=DECISION_TIME + timedelta(minutes=2),
            )
            second = exporter.export(
                view.view_id,
                created_at=DECISION_TIME + timedelta(minutes=3),
            )

            self.assertTrue(first.writes_performed)
            self.assertFalse(second.writes_performed)
            self.assertEqual(first.artifact, second.artifact)
            payload = Path(first.artifact.storage_uri.removeprefix("file://")).read_bytes()
            self.assertEqual(
                first.artifact.content_hash,
                "sha256:" + hashlib.sha256(payload).hexdigest(),
            )
            document = json.loads(payload)
            self.assertEqual(document["artifact_schema_version"], "investment-view:v1")
            self.assertEqual(document["investment_view_content_hash"], view.content_hash)
            self.assertEqual(document["investment_view"]["view_id"], view.view_id)
            self.assertEqual(governance.list_artifacts(), (first.artifact,))
            lineage = governance.list_lineage()
            self.assertIn(
                (view.view_id, first.artifact.artifact_id, "frozen_as"),
                tuple(
                    (edge.upstream_id, edge.downstream_id, edge.relation)
                    for edge in lineage
                ),
            )
            for identifier in (
                *view.dataset_version_ids,
                *view.feature_version_ids,
                view.model_version_id,
                view.run_id,
            ):
                self.assertTrue(
                    any(
                        edge.upstream_id == identifier
                        and edge.downstream_id == first.artifact.artifact_id
                        for edge in lineage
                    )
                )

    def test_missing_view_or_unsuccessful_run_fails_before_object_write(self) -> None:
        expected = InMemoryExpectedReturnLedgerRepository()
        governance = InMemoryGovernanceRepository()
        with TemporaryDirectory() as directory:
            root = Path(directory) / "objects"
            exporter = InvestmentViewArtifactExporter(
                ExpectedReturnLedgerService(expected),
                GovernanceLedger(governance),
                LocalRawObjectStore(root),
            )
            with self.assertRaisesRegex(LookupError, "InvestmentView"):
                exporter.export(
                    "investment-view:missing",
                    created_at=DECISION_TIME + timedelta(minutes=2),
                )
            self.assertFalse(root.exists())

            view = ExpectedReturnCompilerV0().compile(request())
            ExpectedReturnLedgerService(expected).record_view(view)
            with self.assertRaisesRegex(PermissionError, "succeeded run"):
                exporter.export(
                    view.view_id,
                    created_at=DECISION_TIME + timedelta(minutes=2),
                )
            self.assertFalse(root.exists())

    def test_invalid_artifact_time_fails_before_object_write(self) -> None:
        expected = InMemoryExpectedReturnLedgerRepository()
        governance = InMemoryGovernanceRepository()
        view = ExpectedReturnCompilerV0().compile(request())
        ExpectedReturnLedgerService(expected).record_view(view)
        run = succeeded_run()
        GovernanceLedger(governance).register_run(run)

        with TemporaryDirectory() as directory:
            root = Path(directory) / "objects"
            exporter = InvestmentViewArtifactExporter(
                ExpectedReturnLedgerService(expected),
                GovernanceLedger(governance),
                LocalRawObjectStore(root),
            )
            with self.assertRaisesRegex(ValueError, "timezone-aware"):
                exporter.export(
                    view.view_id,
                    created_at=DECISION_TIME.replace(tzinfo=None),
                )
            with self.assertRaisesRegex(ValueError, "cannot precede"):
                exporter.export(
                    view.view_id,
                    created_at=run.finished_at - timedelta(microseconds=1),  # type: ignore[operator]
                )
            self.assertFalse(root.exists())

    def test_governance_hash_conflict_fails_before_object_write(self) -> None:
        expected = InMemoryExpectedReturnLedgerRepository()
        governance = InMemoryGovernanceRepository()
        view = ExpectedReturnCompilerV0().compile(request())
        ExpectedReturnLedgerService(expected).record_view(view)
        run = succeeded_run()
        ledger = GovernanceLedger(governance)
        ledger.register_run(run)
        view_document = view.hash_payload()
        view_document["content_hash"] = view.content_hash
        payload = json.dumps(
            {
                "artifact_schema_version": "investment-view:v1",
                "investment_view_content_hash": view.content_hash,
                "investment_view": view_document,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        content_hash = "sha256:" + hashlib.sha256(payload).hexdigest()
        ledger.register_artifact(
            Artifact(
                artifact_id="artifact:conflicting-owner",
                run_id=view.run_id,
                content_hash=content_hash,
                media_type="application/json",
                storage_uri="file:///already-registered",
                created_at=DECISION_TIME + timedelta(minutes=2),
            )
        )

        with TemporaryDirectory() as directory:
            root = Path(directory) / "objects"
            exporter = InvestmentViewArtifactExporter(
                ExpectedReturnLedgerService(expected),
                ledger,
                LocalRawObjectStore(root),
            )
            with self.assertRaisesRegex(RuntimeError, "content hash conflict"):
                exporter.export(
                    view.view_id,
                    created_at=DECISION_TIME + timedelta(minutes=3),
                )
            self.assertFalse(root.exists())


if __name__ == "__main__":
    unittest.main()
