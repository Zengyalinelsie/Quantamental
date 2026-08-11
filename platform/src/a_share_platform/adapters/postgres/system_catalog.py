"""PostgreSQL read-only adapter for the System data-management workspace."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Any, Protocol, cast

import psycopg

from a_share_platform.application.system_catalog import (
    CoverageReportEntry,
    DatasetCatalogEntry,
    IngestionCheckpointEntry,
    IngestionJobEntry,
    LineageCatalogEntry,
    QualityReportEntry,
)


class QueryResult(Protocol):
    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise TypeError("stored JSON value is not an object")
    return {str(key): item for key, item in value.items()}


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, (list, tuple)):
        raise TypeError("stored JSON value is not an array")
    return tuple(str(item) for item in value)


class PostgresSystemCatalogReader:
    """Open one read-only transaction per API read; never retain or expose a DSN."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresSystemCatalogReader:
        if not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(read_only=True)"

    def _read(self, query: str) -> list[tuple[object, ...]]:
        with self._connection_factory() as connection, connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            return connection.execute(query).fetchall()

    def list_datasets(self) -> tuple[DatasetCatalogEntry, ...]:
        rows = self._read(
            """
            SELECT dataset_version_id, content_hash, created_at, schema_version, metadata
            FROM governance.dataset_versions ORDER BY created_at DESC, dataset_version_id
            """
        )
        return tuple(
            DatasetCatalogEntry(
                dataset_version_id=str(row[0]),
                content_hash=str(row[1]),
                created_at=cast(datetime, row[2]),
                schema_version=str(row[3]),
                metadata=_json_object(row[4]),
            )
            for row in rows
        )

    def list_quality_reports(self) -> tuple[QualityReportEntry, ...]:
        return tuple(self._quality_from_row(row) for row in self._quality_rows())

    def _quality_rows(self) -> list[tuple[object, ...]]:
        return self._read(
            """
            SELECT quality_report_id, dataset_version_id, job_id, status,
                   checks_passed, checks_failed, issue_counts, warnings, created_at
            FROM governance.dataset_quality_reports ORDER BY created_at DESC, quality_report_id
            """
        )

    def _coverage_rows(self) -> list[tuple[object, ...]]:
        return self._read(
            """
            SELECT coverage_report_id, dataset_version_id, job_id, scope_id,
                   data_domain, start_date, end_date, expected_rows, observed_rows,
                   coverage_ratio, warnings, created_at
            FROM governance.dataset_coverage_reports ORDER BY created_at DESC, coverage_report_id
            """
        )

    def list_lineage(self) -> tuple[LineageCatalogEntry, ...]:
        rows = self._read(
            """
            SELECT upstream_id, downstream_id, relation
            FROM governance.lineage_edges ORDER BY upstream_id, downstream_id, relation
            """
        )
        return tuple(
            LineageCatalogEntry(
                upstream_id=str(row[0]),
                downstream_id=str(row[1]),
                relation=str(row[2]),
            )
            for row in rows
        )

    def list_jobs(self) -> tuple[IngestionJobEntry, ...]:
        job_rows = self._read(
            """
            SELECT job_id, plan_id, provider_id, status, output_trust_state,
                   start_date, end_date, created_at, updated_at, dataset_version_id,
                   failure_reasons
            FROM governance.ingestion_jobs ORDER BY created_at DESC, job_id
            """
        )
        checkpoint_rows = self._read(
            """
            SELECT job_id, checkpoint_key, scope_id, data_domain, market, status,
                   processed_rows, rejected_rows, provider_id, updated_at, error, warnings
            FROM governance.ingestion_checkpoints ORDER BY job_id, checkpoint_key
            """
        )
        quality_rows = self._quality_rows()
        coverage_rows = self._coverage_rows()
        checkpoints: defaultdict[str, list[IngestionCheckpointEntry]] = defaultdict(list)
        quality: defaultdict[str, list[QualityReportEntry]] = defaultdict(list)
        coverage: defaultdict[str, list[CoverageReportEntry]] = defaultdict(list)
        for row in checkpoint_rows:
            checkpoints[str(row[0])].append(self._checkpoint_from_row(row))
        for row in quality_rows:
            quality[str(row[2])].append(self._quality_from_row(row))
        for row in coverage_rows:
            coverage[str(row[2])].append(self._coverage_from_row(row))
        return tuple(
            IngestionJobEntry(
                job_id=str(row[0]),
                plan_id=str(row[1]),
                provider_id=str(row[2]),
                status=str(row[3]),
                output_trust_state=str(row[4]),
                start_date=cast(date, row[5]),
                end_date=cast(date, row[6]),
                created_at=cast(datetime, row[7]),
                updated_at=cast(datetime, row[8]),
                dataset_version_id=None if row[9] is None else str(row[9]),
                failure_reasons=_string_tuple(row[10]),
                checkpoints=tuple(checkpoints[str(row[0])]),
                quality_reports=tuple(quality[str(row[0])]),
                coverage_reports=tuple(coverage[str(row[0])]),
            )
            for row in job_rows
        )

    @staticmethod
    def _quality_from_row(row: tuple[object, ...]) -> QualityReportEntry:
        return QualityReportEntry(
            quality_report_id=str(row[0]),
            dataset_version_id=str(row[1]),
            job_id=str(row[2]),
            status=str(row[3]),
            checks_passed=int(cast(int, row[4])),
            checks_failed=int(cast(int, row[5])),
            issue_counts={
                key: int(cast(int, value)) for key, value in _json_object(row[6]).items()
            },
            warnings=_string_tuple(row[7]),
            created_at=cast(datetime, row[8]),
        )

    @staticmethod
    def _coverage_from_row(row: tuple[object, ...]) -> CoverageReportEntry:
        return CoverageReportEntry(
            coverage_report_id=str(row[0]),
            dataset_version_id=str(row[1]),
            job_id=str(row[2]),
            scope_id=str(row[3]),
            data_domain=str(row[4]),
            start_date=cast(date, row[5]),
            end_date=cast(date, row[6]),
            expected_rows=None if row[7] is None else int(cast(int, row[7])),
            observed_rows=int(cast(int, row[8])),
            coverage_ratio=None if row[9] is None else float(cast(float, row[9])),
            warnings=_string_tuple(row[10]),
            created_at=cast(datetime, row[11]),
        )

    @staticmethod
    def _checkpoint_from_row(row: tuple[object, ...]) -> IngestionCheckpointEntry:
        return IngestionCheckpointEntry(
            checkpoint_key=str(row[1]),
            scope_id=str(row[2]),
            data_domain=str(row[3]),
            market=None if row[4] is None else str(row[4]),
            status=str(row[5]),
            processed_rows=int(cast(int, row[6])),
            rejected_rows=int(cast(int, row[7])),
            provider_id=None if row[8] is None else str(row[8]),
            updated_at=cast(datetime, row[9]),
            error=None if row[10] is None else str(row[10]),
            warnings=_string_tuple(row[11]),
        )
