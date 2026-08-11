import unittest
from datetime import UTC, date, datetime

from a_share_platform.adapters.postgres.financial_aggregate_coverage import (
    PostgresFinancialAggregateCoverageRepository,
)
from a_share_platform.application.financial_aggregate_coverage import (
    FinancialAggregateCoverageSnapshot,
)
from a_share_platform.domain.backfill import (
    BackfillDataDomain,
    DatasetCoverageReport,
)

NOW = datetime(2026, 8, 11, 5, tzinfo=UTC)


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class SequenceConnection:
    def __init__(self, responses: list[list[tuple[object, ...]]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        rows = [] if not self.responses else self.responses.pop(0)
        return FakeResult(rows)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class PostgresFinancialAggregateCoverageRepositoryTest(unittest.TestCase):
    def test_snapshot_cross_checks_receipts_observations_and_distinct_symbols(self) -> None:
        connection = SequenceConnection(
            [[("job:financial:test", 720, 2120, 2120, ["SH.600000", "SZ.000001"], NOW)]]
        )
        repository = PostgresFinancialAggregateCoverageRepository(connection)

        snapshot = repository.get_snapshot("job:financial:test")

        self.assertEqual(
            snapshot,
            FinancialAggregateCoverageSnapshot(
                job_id="job:financial:test",
                completed_work_units=720,
                receipt_observation_count=2120,
                persisted_observation_count=2120,
                observed_symbols=("SH.600000", "SZ.000001"),
                completed_at=NOW,
            ),
        )
        query, params = connection.calls[0]
        self.assertIn("financial_backfill_persist_receipts", query)
        self.assertIn("normalized_current_financial_observations", query)
        self.assertIn("status = 'succeeded'", query)
        self.assertEqual(params, ("job:financial:test", "job:financial:test"))

    def test_coverage_report_round_trip_fields_are_explicit(self) -> None:
        row = (
            "coverage:job:financial:test:aggregate:v1",
            "dataset:financial:aggregate:v1",
            "job:financial:test",
            "index:000300",
            "financial_statement",
            date(2018, 12, 31),
            date(2025, 12, 31),
            720,
            720,
            1.0,
            ["canonical_observation_count=2120"],
            NOW,
        )
        connection = SequenceConnection([[row]])
        repository = PostgresFinancialAggregateCoverageRepository(connection)

        report = repository.get_coverage_report(row[0])

        self.assertEqual(
            report,
            DatasetCoverageReport(
                report_id=row[0],
                dataset_version_id=row[1],
                job_id=row[2],
                scope_id=row[3],
                domain=BackfillDataDomain.FINANCIAL_STATEMENT,
                start_date=row[5],
                end_date=row[6],
                expected_rows=720,
                observed_rows=720,
                coverage_ratio=1.0,
                warnings=("canonical_observation_count=2120",),
                created_at=NOW,
            ),
        )


if __name__ == "__main__":
    unittest.main()
