"""PostgreSQL registration for immutable dataset versions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, cast

from a_share_platform.domain.governance import DatasetVersion, VersionConflictError


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _normalize_metadata(value: Mapping[str, object]) -> dict[str, object]:
    try:
        normalized = json.loads(
            json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        )
    except (TypeError, ValueError) as error:
        raise ValueError("dataset metadata must be JSON serializable") from error
    if not isinstance(normalized, dict):
        raise TypeError("dataset metadata must be a JSON object")
    manifest = normalized.get("manifest")
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("dataset metadata must contain a non-empty manifest object")
    return cast(dict[str, object], normalized)


def _metadata_from_row(value: object) -> dict[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise TypeError("stored dataset metadata is not a JSON object")
    return cast(dict[str, object], value)


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

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> DatasetVersion:
        expected_metadata = _normalize_metadata(
            metadata if metadata is not None else self._registration_manifest(value)
        )
        self._connection.execute(
            """
            INSERT INTO dataset_versions (
                dataset_version_id, content_hash, created_at, schema_version, metadata
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (dataset_version_id) DO NOTHING
            """,
            (
                value.dataset_version_id,
                value.content_hash,
                value.created_at,
                value.schema_version,
                _json_parameter(expected_metadata),
            ),
        )
        row = self._connection.execute(
            """
            SELECT dataset_version_id, content_hash, created_at, schema_version, metadata
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
        if _metadata_from_row(row[4]) != expected_metadata:
            raise VersionConflictError(
                f"immutable dataset metadata conflict: {value.dataset_version_id}"
            )
        return stored

    def dataset_metadata(self, dataset_version_id: str) -> dict[str, object] | None:
        if not dataset_version_id.strip():
            raise ValueError("dataset_version_id must not be empty")
        row = self._connection.execute(
            """
            SELECT dataset_version_id, content_hash, created_at, schema_version, metadata
            FROM dataset_versions WHERE dataset_version_id = %s
            """,
            (dataset_version_id,),
        ).fetchone()
        if row is None:
            return None
        return _metadata_from_row(row[4])

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

    @staticmethod
    def _registration_manifest(value: DatasetVersion) -> dict[str, object]:
        """Keep a minimal immutable manifest when the caller has no richer one."""

        return {
            "manifest": {
                "dataset_version_id": value.dataset_version_id,
                "content_hash": value.content_hash,
                "created_at": value.created_at.isoformat(),
                "schema_version": value.schema_version,
            }
        }
