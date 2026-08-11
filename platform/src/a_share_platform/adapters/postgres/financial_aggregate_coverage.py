"""PostgreSQL adapter for immutable aggregate financial coverage evidence."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Protocol, cast

from a_share_platform.adapters.postgres.backfill import PostgresBackfillRepository
from a_share_platform.adapters.postgres.financial_backfill_job import (
    PostgresFinancialBackfillJobRepository,
)
from a_share_platform.application.financial_aggregate_coverage import (
    FinancialAggregateCoverageSnapshot,
)
from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.domain.backfill import BackfillDataDomain, DatasetCoverageReport


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


def _list(value: object, label: str) -> list[object]:
    if isinstance(value, str):
        value = json.loads(value)
    wrapped = getattr(value, "obj", None)
    if wrapped is not None:
        value = wrapped
    if not isinstance(value, list):
        raise TypeError(f"stored {label} must be a JSON array")
    return value


class PostgresFinancialAggregateCoverageRepository:
    """Cross-check receipt and observation counts before saving one report."""

    _COVERAGE_SELECT = """
        SELECT coverage_report_id, dataset_version_id, job_id, scope_id,
               data_domain, start_date, end_date, expected_rows, observed_rows,
               coverage_ratio, warnings, created_at
        FROM governance.dataset_coverage_reports
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._jobs = PostgresFinancialBackfillJobRepository(connection)
        self._backfills = PostgresBackfillRepository(connection)

    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None:
        return self._jobs.get_job(job_id)

    def get_snapshot(self, job_id: str) -> FinancialAggregateCoverageSnapshot:
        row = self._connection.execute(
            """
            WITH completed AS (
                SELECT checkpoints.job_id,
                       COUNT(*) AS completed_work_units,
                       COALESCE(SUM(receipts.observation_count), 0)
                           AS receipt_observation_count,
                       MAX(checkpoints.updated_at) AS completed_at
                FROM governance.ingestion_checkpoints AS checkpoints
                JOIN governance.financial_backfill_persist_receipts AS receipts
                  ON receipts.job_id = checkpoints.job_id
                 AND receipts.checkpoint_key = checkpoints.checkpoint_key
                WHERE checkpoints.job_id = %s
                  AND checkpoints.data_domain = 'financial_statement'
                  AND checkpoints.status = 'succeeded'
                GROUP BY checkpoints.job_id
            ), observed AS (
                SELECT COUNT(*) AS persisted_observation_count,
                       COALESCE(
                           ARRAY_AGG(DISTINCT canonical_symbol ORDER BY canonical_symbol),
                           ARRAY[]::TEXT[]
                       ) AS observed_symbols
                FROM observation.normalized_current_financial_observations
                WHERE job_id = %s
            )
            SELECT completed.job_id, completed.completed_work_units,
                   completed.receipt_observation_count,
                   observed.persisted_observation_count,
                   observed.observed_symbols,
                   completed.completed_at
            FROM completed CROSS JOIN observed
            """,
            (job_id, job_id),
        ).fetchone()
        if row is None:
            raise LookupError(f"completed financial checkpoints do not exist: {job_id}")
        return FinancialAggregateCoverageSnapshot(
            job_id=str(row[0]),
            completed_work_units=int(cast(int, row[1])),
            receipt_observation_count=int(cast(int, row[2])),
            persisted_observation_count=int(cast(int, row[3])),
            observed_symbols=tuple(str(value) for value in cast(list[object], row[4])),
            completed_at=cast(datetime, row[5]),
        )

    def get_coverage_report(self, report_id: str) -> DatasetCoverageReport | None:
        row = self._connection.execute(
            self._COVERAGE_SELECT + " WHERE coverage_report_id = %s",
            (report_id,),
        ).fetchone()
        if row is None:
            return None
        expected_rows = None if row[7] is None else int(cast(int, row[7]))
        ratio = None if row[9] is None else float(cast(float, row[9]))
        return DatasetCoverageReport(
            report_id=str(row[0]),
            dataset_version_id=str(row[1]),
            job_id=str(row[2]),
            scope_id=str(row[3]),
            domain=BackfillDataDomain(str(row[4])),
            start_date=cast(date, row[5]),
            end_date=cast(date, row[6]),
            expected_rows=expected_rows,
            observed_rows=int(cast(int, row[8])),
            coverage_ratio=ratio,
            warnings=tuple(str(value) for value in _list(row[10], "coverage warnings")),
            created_at=cast(datetime, row[11]),
        )

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport:
        return self._backfills.save_coverage_report(value)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


__all__ = ["PostgresFinancialAggregateCoverageRepository"]
