"""PostgreSQL evidence and persistence for cross-job financial cohort audits."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, cast

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.adapters.postgres.financial_backfill_job import (
    PostgresFinancialBackfillJobRepository,
)
from a_share_platform.application.financial_backfill_job import FinancialBackfillJobRecord
from a_share_platform.application.financial_cohort_audit import FinancialCohortAuditSnapshot
from a_share_platform.domain.governance import DatasetVersion, LineageEdge


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


class PostgresFinancialCohortAuditRepository:
    """Read all component ledgers in one snapshot and freeze one audit dataset."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._jobs = PostgresFinancialBackfillJobRepository(connection)
        self._datasets = PostgresDatasetVersionRepository(connection)

    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None:
        return self._jobs.get_job(job_id)

    def get_snapshot(self, job_ids: tuple[str, ...]) -> FinancialCohortAuditSnapshot:
        normalized = tuple(sorted(job_ids))
        if not normalized or len(normalized) != len(set(normalized)):
            raise ValueError("job_ids must be non-empty and unique")
        parameters = (list(normalized),)
        row = self._connection.execute(
            """
            WITH requested_jobs AS (
                SELECT UNNEST(%s::TEXT[]) AS job_id
            ), completed AS (
                SELECT COUNT(*) AS completed_work_units,
                       COALESCE(SUM(receipts.observation_count), 0)
                           AS receipt_observation_count,
                       COUNT(*) FILTER (WHERE receipts.observation_count = 0)
                           AS zero_observation_work_units,
                       COALESCE(SUM(checkpoints.rejected_rows), 0) AS rejected_rows,
                       MAX(checkpoints.updated_at) AS completed_at
                FROM requested_jobs
                JOIN governance.ingestion_checkpoints AS checkpoints USING (job_id)
                JOIN governance.financial_backfill_persist_receipts AS receipts
                  ON receipts.job_id = checkpoints.job_id
                 AND receipts.checkpoint_key = checkpoints.checkpoint_key
                WHERE checkpoints.data_domain = 'financial_statement'
                  AND checkpoints.status = 'succeeded'
            ), observed AS (
                SELECT COUNT(*) AS persisted_observation_count,
                       COALESCE(
                           ARRAY_AGG(DISTINCT observations.canonical_symbol
                                     ORDER BY observations.canonical_symbol),
                           ARRAY[]::TEXT[]
                       ) AS observed_symbols
                FROM requested_jobs
                JOIN observation.normalized_current_financial_observations AS observations
                  USING (job_id)
            ), quality AS (
                SELECT COUNT(*) AS quality_report_count,
                       COUNT(*) FILTER (WHERE reports.status = 'passed')
                           AS passed_quality_reports,
                       COUNT(*) FILTER (WHERE reports.status = 'warned')
                           AS warned_quality_reports,
                       COUNT(*) FILTER (WHERE reports.status = 'failed')
                           AS failed_quality_reports
                FROM requested_jobs
                JOIN governance.dataset_quality_reports AS reports USING (job_id)
            ), coverage AS (
                SELECT COUNT(*) AS coverage_report_count,
                       COUNT(*) FILTER (WHERE reports.coverage_ratio = 1.0)
                           AS full_coverage_reports,
                       COUNT(*) FILTER (
                           WHERE reports.coverage_ratio > 0.0
                             AND reports.coverage_ratio < 1.0
                       ) AS partial_coverage_reports,
                       COUNT(*) FILTER (WHERE reports.coverage_ratio = 0.0)
                           AS zero_coverage_reports
                FROM requested_jobs
                JOIN governance.dataset_coverage_reports AS reports USING (job_id)
            )
            SELECT completed.completed_work_units,
                   completed.receipt_observation_count,
                   observed.persisted_observation_count,
                   completed.zero_observation_work_units,
                   completed.rejected_rows,
                   observed.observed_symbols,
                   coverage.coverage_report_count,
                   coverage.full_coverage_reports,
                   coverage.partial_coverage_reports,
                   coverage.zero_coverage_reports,
                   quality.quality_report_count,
                   quality.passed_quality_reports,
                   quality.warned_quality_reports,
                   quality.failed_quality_reports,
                   completed.completed_at
            FROM completed CROSS JOIN observed CROSS JOIN quality CROSS JOIN coverage
            """,
            parameters,
        ).fetchone()
        if row is None or not isinstance(row[14], datetime):
            raise LookupError("completed financial cohort audit inputs do not exist")
        issue_rows = self._connection.execute(
            """
            WITH requested_jobs AS (
                SELECT UNNEST(%s::TEXT[]) AS job_id
            ), quality_issue_counts AS (
                SELECT issues.key AS issue_code,
                       SUM(issues.value::INTEGER) AS issue_count
                FROM requested_jobs
                JOIN governance.dataset_quality_reports AS reports USING (job_id)
                CROSS JOIN LATERAL JSONB_EACH_TEXT(reports.issue_counts) AS issues
                GROUP BY issues.key
            )
            SELECT issue_code, issue_count
            FROM quality_issue_counts
            WHERE issue_count > 0
            ORDER BY issue_code
            """,
            parameters,
        ).fetchall()
        observed = cast(Sequence[object], row[5])
        return FinancialCohortAuditSnapshot(
            job_ids=normalized,
            completed_work_units=int(cast(int, row[0])),
            receipt_observation_count=int(cast(int, row[1])),
            persisted_observation_count=int(cast(int, row[2])),
            zero_observation_work_units=int(cast(int, row[3])),
            rejected_rows=int(cast(int, row[4])),
            observed_symbols=tuple(str(value) for value in observed),
            coverage_report_count=int(cast(int, row[6])),
            full_coverage_reports=int(cast(int, row[7])),
            partial_coverage_reports=int(cast(int, row[8])),
            zero_coverage_reports=int(cast(int, row[9])),
            quality_report_count=int(cast(int, row[10])),
            passed_quality_reports=int(cast(int, row[11])),
            warned_quality_reports=int(cast(int, row[12])),
            failed_quality_reports=int(cast(int, row[13])),
            quality_issue_counts=tuple(
                (str(issue_code), int(cast(int, issue_count)))
                for issue_code, issue_count in issue_rows
            ),
            completed_at=cast(datetime, row[14]),
        )

    def get_dataset_metadata(self, dataset_version_id: str) -> dict[str, object] | None:
        return self._datasets.dataset_metadata(dataset_version_id)

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: dict[str, object],
    ) -> DatasetVersion:
        return self._datasets.register_dataset(value, metadata=metadata)

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        self._connection.execute(
            """
            INSERT INTO governance.lineage_edges (upstream_id, downstream_id, relation)
            VALUES (%s, %s, %s)
            ON CONFLICT (upstream_id, downstream_id, relation) DO NOTHING
            """,
            (value.upstream_id, value.downstream_id, value.relation),
        )
        return value

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()


__all__ = ["PostgresFinancialCohortAuditRepository"]
