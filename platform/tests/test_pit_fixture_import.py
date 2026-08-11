import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from a_share_platform.adapters.postgres.pit_fixture_import import (
    PostgresPITFixtureImporter,
)
from a_share_platform.adapters.postgres.schema_layers import qualified_table
from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.pit_fixtures import PITFixturePack

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PLATFORM_ROOT / "fixtures" / "p3" / "pit_fixture_pack.v1.json"
EVIDENCE_ROOT = PLATFORM_ROOT / "var" / "private-research" / "p3-fixtures" / "raw"


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(self, *, conflict_table: str | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.conflict_table = conflict_table

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "FROM canonical.identifier_history" in query:
            code = str(params[0])
            return FakeResult([(f"company:{code}", f"security:{code}")])
        if self.conflict_table and f"INSERT INTO {qualified_table(self.conflict_table)}" in query:
            return FakeResult([])
        if "RETURNING" in query:
            return FakeResult([(params[0],)])
        return FakeResult([])

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class PostgresPITFixtureImporterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = PITFixturePack.load(MANIFEST)
        self.importer = PostgresPITFixtureImporter(self.pack, EVIDENCE_ROOT)

    def test_preview_is_read_only_and_reports_real_pack_scope(self) -> None:
        connection = FakeConnection()
        summary = self.importer.preview()
        self.assertEqual(summary.company_count, 4)
        self.assertEqual(summary.official_evidence_count, 8)
        self.assertEqual(summary.revision_chain_count, 2)
        self.assertEqual(summary.official_fact_count, 12)
        self.assertEqual(connection.calls, [])

    def test_execute_requires_private_local_ack_before_database_or_file_access(self) -> None:
        connection = FakeConnection()
        with self.assertRaisesRegex(PermissionError, "private-local"):
            self.importer.execute(connection, private_local_research_ack=False)
        self.assertEqual(connection.calls, [])

    def test_execute_is_transactional_and_persists_evidence_facts_governance_and_mismatch(self) -> None:
        connection = FakeConnection()
        with patch.object(PITFixturePack, "verify_raw_evidence"):
            summary = self.importer.execute(
                connection,
                private_local_research_ack=True,
            )
        sql = "\n".join(query for query, _ in connection.calls)
        for table in (
            "raw_objects",
            "official_disclosures",
            "canonical_metrics",
            "metric_mapping_versions",
            "provider_field_mappings",
            "dataset_versions",
            "financial_fact_observations",
            "financial_authority_rules",
            "lineage_edges",
            "ingestion_jobs",
            "dataset_quality_reports",
        ):
            self.assertIn(f"INSERT INTO {qualified_table(table)}", sql)
        self.assertGreater(summary.persisted_fact_count, summary.official_fact_count)
        self.assertGreater(summary.blocking_mismatch_count, 0)
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)

    def test_immutable_identifier_conflict_rolls_back_instead_of_overwriting(self) -> None:
        connection = FakeConnection(conflict_table="raw_objects")
        with (
            patch.object(PITFixturePack, "verify_raw_evidence"),
            self.assertRaisesRegex(VersionConflictError, "raw_objects"),
        ):
            self.importer.execute(
                connection,
                private_local_research_ack=True,
            )
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)

    def test_missing_master_identity_can_be_bootstrapped_only_from_private_real_snapshot(self) -> None:
        class MissingIdentityConnection(FakeConnection):
            def __init__(self) -> None:
                super().__init__()
                self.bootstrapped = False

            def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
                if "FROM canonical.identifier_history" in query or "FROM canonical.listings listing" in query:
                    code = str(params[0]).removeprefix("listing:XSHE:")
                    if code == "002898" and not self.bootstrapped:
                        self.calls.append((query, params))
                        return FakeResult([])
                if "INSERT INTO canonical.companies" in query and "002898" in str(params[0]):
                    self.bootstrapped = True
                return super().execute(query, params)

        snapshot = {
            "retrieved_at": "2026-08-10T21:15:19.903113+08:00",
            "provider_id": "baostock_sdk.query_stock_basic",
            "source_url": "https://www.baostock.com",
            "rows": [
                {
                    "code": "SZ.002898",
                    "code_name": "赛隆退",
                    "listed_on": "2017-09-12",
                    "delisted_on": "2026-07-17",
                    "status": "terminated",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "identity.json"
            snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
            importer = PostgresPITFixtureImporter(
                self.pack,
                EVIDENCE_ROOT,
                identity_snapshot_path=snapshot_path,
            )
            connection = MissingIdentityConnection()
            with patch.object(PITFixturePack, "verify_raw_evidence"):
                importer.execute(connection, private_local_research_ack=True)
        sql = "\n".join(query for query, _ in connection.calls)
        self.assertIn("INSERT INTO canonical.companies", sql)
        self.assertIn("INSERT INTO canonical.securities", sql)
        self.assertIn("INSERT INTO canonical.listings", sql)
        self.assertIn("normalized_current", str(connection.calls))
        self.assertTrue(connection.bootstrapped)


if __name__ == "__main__":
    unittest.main()
