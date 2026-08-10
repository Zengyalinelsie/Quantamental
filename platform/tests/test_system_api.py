import unittest
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.system_catalog import StaticSystemCatalogReader
from a_share_platform.api.app import create_app
from a_share_platform.application.system_catalog import (
    CoverageReportEntry,
    DatasetCatalogEntry,
    IngestionCheckpointEntry,
    IngestionJobEntry,
    LineageCatalogEntry,
    QualityReportEntry,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


def reader() -> StaticSystemCatalogReader:
    quality = QualityReportEntry(
        quality_report_id="quality:xshe:v1",
        dataset_version_id="dataset:xshe:v1",
        job_id="job:xshe:v1",
        status="passed",
        checks_passed=1,
        checks_failed=0,
        issue_counts={},
        warnings=(),
        created_at=NOW,
    )
    coverage = CoverageReportEntry(
        coverage_report_id="coverage:xshe:v1",
        dataset_version_id="dataset:xshe:v1",
        job_id="job:xshe:v1",
        scope_id="a-share:security-master",
        data_domain="security_master",
        start_date=date(2018, 1, 1),
        end_date=date(2026, 8, 10),
        expected_rows=331,
        observed_rows=330,
        coverage_ratio=330 / 331,
        warnings=("SZ.302132 requires code-history resolution",),
        created_at=NOW,
    )
    checkpoint = IngestionCheckpointEntry(
        checkpoint_key="security_master:a-share-security-master:XSHE",
        scope_id="a-share:security-master",
        data_domain="security_master",
        market="XSHE",
        status="failed",
        processed_rows=330,
        rejected_rows=0,
        provider_id="a_share_identity_universe",
        updated_at=NOW,
        error="missing_symbols=SZ.302132",
        warnings=(),
    )
    return StaticSystemCatalogReader(
        datasets=(
            DatasetCatalogEntry(
                dataset_version_id="dataset:xshe:v1",
                content_hash="sha256:" + "a" * 64,
                created_at=NOW,
                schema_version="security-master:v1",
                metadata={"manifest": {"provider": "a_share_identity_universe"}},
            ),
        ),
        quality_reports=(quality,),
        coverage_reports=(coverage,),
        lineage=(
            LineageCatalogEntry(
                upstream_id="dataset:xshe:v1",
                downstream_id="job:xshe:v1",
                relation="produced_by",
            ),
        ),
        jobs=(
            IngestionJobEntry(
                job_id="job:xshe:v1",
                plan_id="private-local:csi800-identity:xshe:v1",
                provider_id="a_share_identity_universe",
                status="failed",
                output_trust_state="normalized_current",
                start_date=date(2018, 1, 1),
                end_date=date(2026, 8, 10),
                created_at=NOW,
                updated_at=NOW,
                dataset_version_id=None,
                failure_reasons=("missing_symbols=SZ.302132",),
                checkpoints=(checkpoint,),
                quality_reports=(quality,),
                coverage_reports=(coverage,),
            ),
        ),
    )


class SystemApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(create_app(system_catalog=reader()))

    def test_system_endpoints_return_read_only_catalog_quality_lineage_and_jobs(self) -> None:
        cases = {
            "catalog": "dataset:xshe:v1",
            "quality": "quality:xshe:v1",
            "lineage": "produced_by",
            "jobs": "missing_symbols=SZ.302132",
        }
        for resource, expected in cases.items():
            with self.subTest(resource=resource):
                response = self.client.get(f"/api/system/{resource}")
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertIn(expected, str(payload["data"]))
                self.assertEqual(payload["context"]["data_mode"], "current_research")
                self.assertEqual(payload["context"]["deployment_stage"], "research")

    def test_job_payload_keeps_checkpoint_coverage_and_blocking_reason_visible(self) -> None:
        payload = self.client.get("/api/system/jobs").json()["data"][0]
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["checkpoints"][0]["error"], "missing_symbols=SZ.302132")
        self.assertEqual(payload["coverage_reports"][0]["observed_rows"], 330)
        self.assertEqual(payload["coverage_reports"][0]["expected_rows"], 331)
        self.assertEqual(payload["output_trust_state"], "normalized_current")

    def test_default_runtime_system_catalog_is_honestly_empty(self) -> None:
        client = TestClient(create_app())
        for resource in ("catalog", "quality", "lineage", "jobs"):
            with self.subTest(resource=resource):
                self.assertEqual(client.get(f"/api/system/{resource}").json()["data"], [])

    def test_system_api_has_no_write_methods(self) -> None:
        paths = self.client.get("/openapi.json").json()["paths"]
        for path, operations in paths.items():
            if path.startswith("/api/system/"):
                self.assertEqual(set(operations), {"get"})


if __name__ == "__main__":
    unittest.main()
