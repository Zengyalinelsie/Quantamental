import hashlib
import os
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.governance import InMemoryGovernanceRepository
from a_share_platform.adapters.object_store.local import LocalArtifactReader, LocalRawObjectStore
from a_share_platform.adapters.postgres.governance import PostgresGovernanceRepository
from a_share_platform.api.app import anonymous_principal, create_app
from a_share_platform.application.governance_ledger import GovernanceLedger
from a_share_platform.application.permissions import Principal, Role
from a_share_platform.domain.governance import Artifact, RunRecord, RunStatus
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

NOW = datetime(2026, 8, 14, 9, tzinfo=UTC)


def run() -> RunRecord:
    return RunRecord(
        run_id="run:artifact-api:001",
        run_kind="investment_view_compilation",
        status=RunStatus.SUCCEEDED,
        context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
        created_at=NOW,
        code_version="git:abc123",
        environment_fingerprint="python:3.12:test",
        finished_at=NOW,
    )


class InvestmentViewArtifactApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / "objects"
        self.payload = b'{"artifact_schema_version":"investment-view:v1"}'
        self.store = LocalRawObjectStore(self.root)
        self.repository = InMemoryGovernanceRepository()
        ledger = GovernanceLedger(self.repository)
        ledger.register_run(run())
        content_hash = "sha256:" + hashlib.sha256(self.payload).hexdigest()
        self.artifact = ledger.register_artifact(
            Artifact(
                artifact_id="artifact:investment-view:001",
                run_id=run().run_id,
                content_hash=content_hash,
                media_type="application/json",
                storage_uri=self.store.put(self.payload),
                created_at=NOW,
            )
        )
        app = create_app(
            repository=self.repository,
            artifact_reader=LocalArtifactReader(self.root),
        )
        app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "subject:artifact-reader",
            frozenset({Role.RESEARCHER}),
        )
        self.client = TestClient(app)
        self.anonymous_client = TestClient(
            create_app(
                repository=self.repository,
                artifact_reader=LocalArtifactReader(self.root),
            )
        )

    def test_metadata_and_verified_download_are_read_only_and_immutable(self) -> None:
        metadata = self.client.get(f"/api/artifacts/{self.artifact.artifact_id}")
        download = self.client.get(
            f"/api/artifacts/{self.artifact.artifact_id}/download"
        )

        self.assertEqual(metadata.status_code, 200)
        self.assertEqual(metadata.json()["data"]["artifact_id"], self.artifact.artifact_id)
        self.assertNotIn("storage_uri", metadata.json()["data"])
        self.assertEqual(
            metadata.json()["data"]["producer_context"],
            {"data_mode": "current_research", "deployment_stage": "research"},
        )
        self.assertEqual(
            datetime.fromisoformat(
                metadata.json()["context"]["as_of"]
            ),
            NOW,
        )
        self.assertEqual(metadata.json()["context"]["run_id"], self.artifact.run_id)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, self.payload)
        self.assertEqual(download.headers["content-type"], "application/json")
        self.assertEqual(download.headers["etag"], f'"{self.artifact.content_hash}"')
        self.assertEqual(
            download.headers["cache-control"],
            "private, max-age=31536000, immutable",
        )
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertEqual(download.headers["x-content-type-options"], "nosniff")
        paths = self.client.get("/openapi.json").json()["paths"]
        self.assertEqual(set(paths["/api/artifacts/{artifact_id}"]), {"get"})
        self.assertEqual(set(paths["/api/artifacts/{artifact_id}/download"]), {"get"})
        detail_schema = paths["/api/artifacts/{artifact_id}"]["get"]["responses"]["200"]
        self.assertEqual(
            detail_schema["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ArtifactMetadataEnvelope",
        )
        schemas = self.client.get("/openapi.json").json()["components"]["schemas"]
        self.assertNotIn("storage_uri", schemas["ArtifactMetadata"]["properties"])
        for status in ("403", "404", "409", "503"):
            self.assertIn(
                status,
                paths["/api/artifacts/{artifact_id}"]["get"]["responses"],
            )
        download_responses = paths["/api/artifacts/{artifact_id}/download"]["get"][
            "responses"
        ]
        for status in ("200", "304", "400", "403", "404", "409", "503"):
            self.assertIn(status, download_responses)
        self.assertIn("application/octet-stream", download_responses["200"]["content"])
        self.assertIn("ETag", download_responses["200"]["headers"])
        self.assertIn("Cache-Control", download_responses["200"]["headers"])

    def test_missing_artifact_uses_problem_details(self) -> None:
        response = self.client.get("/api/artifacts/artifact:missing")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["type"], "resource_not_found")

    def test_anonymous_cannot_enumerate_or_download_registered_artifacts(self) -> None:
        for path in (
            "/api/artifacts",
            f"/api/artifacts/{self.artifact.artifact_id}",
            f"/api/artifacts/{self.artifact.artifact_id}/download",
            "/api/artifacts/artifact:missing",
        ):
            with self.subTest(path=path):
                response = self.anonymous_client.get(path)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["type"], "permission_denied")

        promoted = self.anonymous_client.get(
            f"/api/artifacts/{self.artifact.artifact_id}",
            params={"deployment_stage": "limited_live"},
        )
        self.assertEqual(promoted.status_code, 403)

        viewer_app = create_app(
            repository=self.repository,
            artifact_reader=LocalArtifactReader(self.root),
        )
        viewer_app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "subject:viewer",
            frozenset({Role.VIEWER}),
        )
        viewer = TestClient(viewer_app).get(
            f"/api/artifacts/{self.artifact.artifact_id}"
        )
        self.assertEqual(viewer.status_code, 403)
        self.assertEqual(viewer.json()["type"], "permission_denied")

    def test_query_cannot_promote_metadata_or_download_context(self) -> None:
        for suffix in ("", "/download"):
            with self.subTest(suffix=suffix):
                response = self.client.get(
                    f"/api/artifacts/{self.artifact.artifact_id}{suffix}",
                    params={"deployment_stage": "limited_live"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["type"], "run_context_override_denied")

    def test_tampered_bytes_fail_closed(self) -> None:
        path = Path(self.artifact.storage_uri.removeprefix("file://"))
        path.write_bytes(b"tampered")

        response = self.client.get(
            f"/api/artifacts/{self.artifact.artifact_id}/download"
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["type"], "artifact_integrity_error")

    def test_matching_if_none_match_returns_verified_not_modified(self) -> None:
        response = self.client.get(
            f"/api/artifacts/{self.artifact.artifact_id}/download",
            headers={"If-None-Match": f'"{self.artifact.content_hash}"'},
        )
        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
        self.assertEqual(response.headers["etag"], f'"{self.artifact.content_hash}"')

    def test_registered_path_outside_controlled_root_is_never_read(self) -> None:
        outside = Path(self.directory.name) / "outside.json"
        outside.write_bytes(self.payload)
        other = Artifact(
            artifact_id="artifact:investment-view:outside",
            run_id=run().run_id,
            content_hash=self.artifact.content_hash,
            media_type="application/json",
            storage_uri=outside.resolve().as_uri(),
            created_at=NOW,
        )
        isolated = InMemoryGovernanceRepository()
        ledger = GovernanceLedger(isolated)
        ledger.register_run(run())
        ledger.register_artifact(other)
        app = create_app(
            repository=isolated,
            artifact_reader=LocalArtifactReader(self.root),
        )
        app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "subject:artifact-reader",
            frozenset({Role.RESEARCHER}),
        )
        client = TestClient(app)

        response = client.get(f"/api/artifacts/{other.artifact_id}/download")

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["type"], "artifact_integrity_error")

    def test_missing_producer_run_and_limited_live_scope_fail_closed(self) -> None:
        class OrphanedGovernanceRepository(InMemoryGovernanceRepository):
            hide_run = False

            def get_run(self, run_id: str):  # type: ignore[no-untyped-def]
                return None if self.hide_run else super().get_run(run_id)

        orphaned = OrphanedGovernanceRepository()
        orphaned.register_run(run())
        orphaned.register_artifact(self.artifact)
        orphaned.hide_run = True
        orphaned_app = create_app(
            repository=orphaned,
            artifact_reader=LocalArtifactReader(self.root),
        )
        orphaned_app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "subject:artifact-reader",
            frozenset({Role.RESEARCHER}),
        )
        orphaned_response = TestClient(orphaned_app).get(
            f"/api/artifacts/{self.artifact.artifact_id}"
        )
        self.assertEqual(orphaned_response.status_code, 409)
        self.assertEqual(orphaned_response.json()["type"], "artifact_integrity_error")

        limited = InMemoryGovernanceRepository()
        limited_run = RunRecord(
            run_id="run:artifact-api:limited-live",
            run_kind="investment_view_compilation",
            status=RunStatus.SUCCEEDED,
            context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.LIMITED_LIVE),
            created_at=NOW,
            code_version="git:abc123",
            environment_fingerprint="python:3.12:test",
            finished_at=NOW,
        )
        limited.register_run(limited_run)
        limited.register_artifact(
            Artifact(
                artifact_id=self.artifact.artifact_id,
                run_id=limited_run.run_id,
                content_hash=self.artifact.content_hash,
                media_type=self.artifact.media_type,
                storage_uri=self.artifact.storage_uri,
                created_at=self.artifact.created_at,
            )
        )
        limited_app = create_app(
            repository=limited,
            artifact_reader=LocalArtifactReader(self.root),
        )
        limited_app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "subject:artifact-reader",
            frozenset({Role.RESEARCHER}),
        )
        limited_response = TestClient(limited_app).get(
            f"/api/artifacts/{self.artifact.artifact_id}/download"
        )
        self.assertEqual(limited_response.status_code, 403)
        self.assertEqual(limited_response.json()["type"], "permission_denied")
        limited_runs = TestClient(limited_app).get("/api/runs")
        self.assertEqual(limited_runs.status_code, 200)
        self.assertEqual(limited_runs.json()["data"], [])

    def test_database_url_composes_postgres_governance_without_connecting(self) -> None:
        with patch.dict(
            os.environ,
            {"ASP_DATABASE_URL": "postgresql://research.invalid/p5"},
            clear=True,
        ):
            app = create_app()

        self.assertIsInstance(
            app.state.governance_repository,
            PostgresGovernanceRepository,
        )

    def test_artifact_root_composition_is_explicit_and_rejects_filesystem_root(self) -> None:
        with patch.dict(
            os.environ,
            {"ASP_ARTIFACT_ROOT": str(self.root)},
            clear=True,
        ):
            app = create_app()
        self.assertIsInstance(app.state.artifact_reader, LocalArtifactReader)

        with (
            patch.dict(os.environ, {"ASP_ARTIFACT_ROOT": "/"}, clear=True),
            self.assertRaisesRegex(ValueError, "filesystem root"),
        ):
            create_app()

    def test_unconfigured_artifact_reader_is_explicitly_unavailable(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            app = create_app(repository=self.repository)
        app.dependency_overrides[anonymous_principal] = lambda: Principal(
            "subject:artifact-reader",
            frozenset({Role.RESEARCHER}),
        )
        response = TestClient(app).get(
            f"/api/artifacts/{self.artifact.artifact_id}/download"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["type"], "artifact_object_unavailable")


if __name__ == "__main__":
    unittest.main()
