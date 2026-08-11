import unittest
from contextlib import AbstractContextManager
from datetime import UTC, date, datetime
from typing import Self

from a_share_platform.adapters.postgres.system_catalog import PostgresSystemCatalogReader

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class FakeTransaction:
    def __init__(self, connection: "FakeConnection") -> None:
        self._connection = connection

    def __enter__(self) -> Self:
        self._connection.transactions += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, rows: dict[str, list[tuple[object, ...]]]) -> None:
        self._rows = rows
        self.calls: list[str] = []
        self.transactions = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append(query)
        if "FROM governance.dataset_versions" in query:
            return FakeResult(self._rows.get("datasets", []))
        if "FROM governance.dataset_quality_reports" in query:
            return FakeResult(self._rows.get("quality", []))
        if "FROM governance.dataset_coverage_reports" in query:
            return FakeResult(self._rows.get("coverage", []))
        if "FROM governance.ingestion_checkpoints" in query:
            return FakeResult(self._rows.get("checkpoints", []))
        if "FROM governance.ingestion_jobs" in query:
            return FakeResult(self._rows.get("jobs", []))
        if "FROM governance.lineage_edges" in query:
            return FakeResult(self._rows.get("lineage", []))
        return FakeResult([])


class Factory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __call__(self) -> AbstractContextManager[FakeConnection]:
        return self.connection


class PostgresSystemCatalogReaderTest(unittest.TestCase):
    def test_each_query_uses_an_explicit_read_only_transaction(self) -> None:
        connection = FakeConnection({"datasets": []})
        reader = PostgresSystemCatalogReader(Factory(connection))

        reader.list_datasets()

        self.assertEqual(connection.transactions, 1)
        self.assertEqual(connection.calls[0].strip(), "SET TRANSACTION READ ONLY")
        self.assertTrue(connection.calls[1].lstrip().startswith("SELECT"))
        self.assertFalse(any("INSERT" in query or "UPDATE" in query for query in connection.calls))

    def test_jobs_restore_json_and_group_checkpoint_quality_and_coverage(self) -> None:
        quality = (
            "quality:v1",
            "dataset:v1",
            "job:v1",
            "passed",
            2,
            0,
            '{"missing": 0}',
            '["current only"]',
            NOW,
        )
        coverage = (
            "coverage:v1",
            "dataset:v1",
            "job:v1",
            "scope:csi800",
            "security_master",
            date(2018, 1, 1),
            date(2026, 8, 10),
            800,
            799,
            799 / 800,
            '["SZ.302132 unresolved"]',
            NOW,
        )
        checkpoint = (
            "job:v1",
            "security-master:XSHE",
            "scope:csi800",
            "security_master",
            "XSHE",
            "failed",
            330,
            0,
            "a_share_identity_universe",
            NOW,
            "missing_symbols=SZ.302132",
            "[]",
        )
        job = (
            "job:v1",
            "private-local:csi800:v1",
            "a_share_identity_universe",
            "failed",
            "normalized_current",
            date(2018, 1, 1),
            date(2026, 8, 10),
            NOW,
            NOW,
            None,
            '["missing_symbols=SZ.302132"]',
        )
        connection = FakeConnection(
            {
                "jobs": [job],
                "checkpoints": [checkpoint],
                "quality": [quality],
                "coverage": [coverage],
            }
        )

        restored = PostgresSystemCatalogReader(Factory(connection)).list_jobs()[0]

        self.assertEqual(restored.failure_reasons, ("missing_symbols=SZ.302132",))
        self.assertEqual(restored.checkpoints[0].error, "missing_symbols=SZ.302132")
        self.assertEqual(restored.quality_reports[0].issue_counts, {"missing": 0})
        self.assertEqual(restored.coverage_reports[0].observed_rows, 799)
        self.assertEqual(connection.transactions, 4)

    def test_reader_repr_does_not_disclose_dsn(self) -> None:
        dsn = "postgresql://private-user:private-password@localhost/private"
        reader = PostgresSystemCatalogReader.from_dsn(dsn)

        self.assertNotIn("private-user", repr(reader))
        self.assertNotIn("private-password", repr(reader))
        self.assertEqual(repr(reader), "PostgresSystemCatalogReader(read_only=True)")


if __name__ == "__main__":
    unittest.main()
