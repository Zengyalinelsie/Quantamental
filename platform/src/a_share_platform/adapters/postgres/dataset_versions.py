"""PostgreSQL registration for immutable dataset versions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, cast

from a_share_platform.domain.governance import DatasetVersion, VersionConflictError


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class PostgresDatasetVersionRepository:
    """Register a dataset before any table takes its foreign key."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def register_dataset(self, value: DatasetVersion) -> DatasetVersion:
        self._connection.execute(
            """
            INSERT INTO dataset_versions (
                dataset_version_id, content_hash, created_at, schema_version
            ) VALUES (%s, %s, %s, %s)
            ON CONFLICT (dataset_version_id) DO NOTHING
            """,
            (
                value.dataset_version_id,
                value.content_hash,
                value.created_at,
                value.schema_version,
            ),
        )
        row = self._connection.execute(
            """
            SELECT dataset_version_id, content_hash, created_at, schema_version
            FROM dataset_versions WHERE dataset_version_id = %s
            """,
            (value.dataset_version_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("dataset version insert was not observable")
        stored = self._from_row(row)
        if stored != value:
            raise VersionConflictError(
                f"immutable dataset identifier conflict: {value.dataset_version_id}"
            )
        return stored

    def list_datasets(self) -> tuple[DatasetVersion, ...]:
        rows = self._connection.execute(
            """
            SELECT dataset_version_id, content_hash, created_at, schema_version
            FROM dataset_versions ORDER BY dataset_version_id
            """
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> DatasetVersion:
        return DatasetVersion(
            dataset_version_id=str(row[0]),
            content_hash=str(row[1]),
            created_at=cast(datetime, row[2]),
            schema_version=str(row[3]),
        )
