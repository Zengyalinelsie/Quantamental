import unittest
from datetime import UTC, datetime

from a_share_platform.adapters.postgres.financial_cohort_audit import (
    PostgresFinancialCohortAuditRepository,
)

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)


class Result:
    def __init__(self, *, one=None, rows=None):  # type: ignore[no-untyped-def]
        self.one = one
        self.rows = rows or []

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self.one

    def fetchall(self):  # type: ignore[no-untyped-def]
        return self.rows


class Connection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> Result:
        self.calls.append((query, params))
        if "quality_issue_counts" in query:
            return Result(rows=[("missing_security", 2)])
        if "completed_work_units" in query:
            return Result(
                one=(
                    12,
                    30,
                    30,
                    2,
                    0,
                    ["SH.600000", "SZ.000001"],
                    12,
                    10,
                    0,
                    2,
                    12,
                    10,
                    2,
                    0,
                    NOW,
                )
            )
        return Result()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class PostgresFinancialCohortAuditRepositoryTest(unittest.TestCase):
    def test_snapshot_cross_checks_receipts_observations_quality_and_rejections(self) -> None:
        connection = Connection()
        repository = PostgresFinancialCohortAuditRepository(connection)  # type: ignore[arg-type]
        job_ids = ("job:pilot", "job:remaining")

        snapshot = repository.get_snapshot(job_ids)

        self.assertEqual(snapshot.job_ids, job_ids)
        self.assertEqual(snapshot.completed_work_units, 12)
        self.assertEqual(snapshot.receipt_observation_count, 30)
        self.assertEqual(snapshot.persisted_observation_count, 30)
        self.assertEqual(snapshot.zero_observation_work_units, 2)
        self.assertEqual(snapshot.observed_symbols, ("SH.600000", "SZ.000001"))
        self.assertEqual(snapshot.coverage_report_count, 12)
        self.assertEqual(snapshot.full_coverage_reports, 10)
        self.assertEqual(snapshot.zero_coverage_reports, 2)
        self.assertEqual(snapshot.quality_issue_counts, (("missing_security", 2),))
        queries = " ".join(query for query, _params in connection.calls)
        self.assertIn("financial_backfill_persist_receipts", queries)
        self.assertIn("normalized_current_financial_observations", queries)
        self.assertIn("dataset_quality_reports", queries)
        self.assertTrue(all(params == (list(job_ids),) for _query, params in connection.calls))


if __name__ == "__main__":
    unittest.main()
