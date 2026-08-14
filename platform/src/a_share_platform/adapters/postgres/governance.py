"""PostgreSQL adapter for the P1 governance ledger contracts."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime
from typing import Protocol, cast

import psycopg

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.domain.governance import (
    Artifact,
    DatasetVersion,
    InvalidRunTransitionError,
    LineageEdge,
    RunRecord,
    RunStatus,
    VersionConflictError,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.governance import GovernanceStoreUnavailable


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


class PostgresGovernanceRepository:
    """Durable datasets, runs, Artifacts, and lineage in `governance.*`."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresGovernanceRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def register_dataset(self, value: DatasetVersion) -> DatasetVersion:
        if not isinstance(value, DatasetVersion):
            raise TypeError("value must be a DatasetVersion")
        try:
            with self._connection_factory() as connection, connection.transaction():
                return PostgresDatasetVersionRepository(connection).register_dataset(value)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise VersionConflictError(
                f"immutable dataset content conflict: {value.dataset_version_id}"
            ) from error

    def list_datasets(self) -> tuple[DatasetVersion, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return PostgresDatasetVersionRepository(connection).list_datasets()
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def register_run(self, value: RunRecord) -> RunRecord:
        if not isinstance(value, RunRecord):
            raise TypeError("value must be a RunRecord")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute(
                    """
                    INSERT INTO governance.run_records (
                        run_id, run_kind, status, data_mode, deployment_stage,
                        started_at, finished_at, failure_reason, code_version,
                        environment_fingerprint
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO NOTHING
                    """,
                    self._run_row(value),
                )
                stored = self._get_run(connection, value.run_id)
                if stored is None:
                    raise RuntimeError("governance run insert was not observable")
                if stored != value:
                    raise VersionConflictError(f"run identifier conflict: {value.run_id}")
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def get_run(self, run_id: str) -> RunRecord | None:
        self._require_identifier(run_id, "run_id")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_run(connection, run_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def append_run_state(self, value: RunRecord) -> RunRecord:
        if not isinstance(value, RunRecord):
            raise TypeError("value must be a RunRecord")
        try:
            with self._connection_factory() as connection, connection.transaction():
                current = self._get_run(connection, value.run_id)
                if current is None:
                    raise KeyError(value.run_id)
                if current.status is RunStatus.PENDING and value.status is RunStatus.RUNNING:
                    expected = replace(current, status=RunStatus.RUNNING)
                elif current.status is RunStatus.RUNNING and value.status.terminal:
                    expected = replace(
                        current,
                        status=value.status,
                        finished_at=value.finished_at,
                        failure_reason=value.failure_reason,
                    )
                else:
                    raise InvalidRunTransitionError(
                        f"run {value.run_id} cannot transition from "
                        f"{current.status.value} to {value.status.value}"
                    )
                if expected != value:
                    raise VersionConflictError(
                        f"run transition changes immutable fields: {value.run_id}"
                    )
                connection.execute(
                    """
                    UPDATE governance.run_records
                    SET status = %s, finished_at = %s, failure_reason = %s
                    WHERE run_id = %s AND status = %s
                    """,
                    (
                        value.status.value,
                        value.finished_at,
                        value.failure_reason,
                        value.run_id,
                        current.status.value,
                    ),
                )
                stored = self._get_run(connection, value.run_id)
                if stored != value:
                    raise InvalidRunTransitionError(
                        f"run transition was not persisted: {value.run_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_runs(self) -> tuple[RunRecord, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(self._run_select() + " ORDER BY run_id").fetchall()
                return tuple(self._run_from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def register_artifact(self, value: Artifact) -> Artifact:
        if not isinstance(value, Artifact):
            raise TypeError("value must be an Artifact")
        try:
            with self._connection_factory() as connection, connection.transaction():
                return self._register_artifact(connection, value)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise VersionConflictError(
                f"immutable artifact content conflict: {value.artifact_id}"
            ) from error

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        self._require_identifier(artifact_id, "artifact_id")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_artifact(connection, artifact_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def get_artifact_by_hash(self, content_hash: str) -> Artifact | None:
        self._require_identifier(content_hash, "content_hash")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._artifact_for_hash(connection, content_hash)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_artifacts(self) -> tuple[Artifact, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(self._artifact_select() + " ORDER BY artifact_id").fetchall()
                return tuple(self._artifact_from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def register_artifact_with_lineage(
        self,
        value: Artifact,
        lineage: tuple[LineageEdge, ...],
    ) -> Artifact:
        if not isinstance(value, Artifact):
            raise TypeError("value must be an Artifact")
        edges = tuple(lineage)
        if any(not isinstance(edge, LineageEdge) for edge in edges):
            raise TypeError("lineage must contain LineageEdge values")
        try:
            with self._connection_factory() as connection, connection.transaction():
                stored = self._register_artifact(connection, value)
                for edge in edges:
                    self._register_lineage(connection, edge)
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise VersionConflictError(
                f"immutable artifact content conflict: {value.artifact_id}"
            ) from error

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        if not isinstance(value, LineageEdge):
            raise TypeError("value must be a LineageEdge")
        try:
            with self._connection_factory() as connection, connection.transaction():
                self._register_lineage(connection, value)
                return value
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_lineage(self) -> tuple[LineageEdge, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    """
                    SELECT upstream_id, downstream_id, relation
                    FROM governance.lineage_edges
                    ORDER BY upstream_id, downstream_id, relation
                    """
                ).fetchall()
                return tuple(LineageEdge(str(row[0]), str(row[1]), str(row[2])) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_lineage_for(self, downstream_id: str) -> tuple[LineageEdge, ...]:
        self._require_identifier(downstream_id, "downstream_id")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    """
                    SELECT upstream_id, downstream_id, relation
                    FROM governance.lineage_edges
                    WHERE downstream_id = %s
                    ORDER BY upstream_id, relation
                    """,
                    (downstream_id,),
                ).fetchall()
                return tuple(LineageEdge(str(row[0]), str(row[1]), str(row[2])) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    @classmethod
    def _register_artifact(cls, connection: Connection, value: Artifact) -> Artifact:
        if cls._get_run(connection, value.run_id) is None:
            raise ValueError(f"artifact run does not exist: {value.run_id}")
        existing = cls._get_artifact(connection, value.artifact_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable artifact identifier conflict: {value.artifact_id}"
                )
            return existing
        hash_owner = cls._artifact_for_hash(connection, value.content_hash)
        if hash_owner is not None:
            raise VersionConflictError(
                f"content hash {value.content_hash} is already bound to "
                f"{hash_owner.artifact_id}"
            )
        connection.execute(
            """
            INSERT INTO governance.artifacts (
                artifact_id, content_hash, media_type, storage_uri, created_at, run_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (artifact_id) DO NOTHING
            """,
            cls._artifact_row(value),
        )
        stored = cls._get_artifact(connection, value.artifact_id)
        if stored is None:
            raise RuntimeError("governance Artifact insert was not observable")
        if stored != value:
            raise VersionConflictError(
                f"immutable artifact identifier conflict: {value.artifact_id}"
            )
        return stored

    @staticmethod
    def _register_lineage(connection: Connection, value: LineageEdge) -> None:
        connection.execute(
            """
            INSERT INTO governance.lineage_edges (
                upstream_id, downstream_id, relation
            ) VALUES (%s, %s, %s)
            ON CONFLICT (upstream_id, downstream_id, relation) DO NOTHING
            """,
            (value.upstream_id, value.downstream_id, value.relation),
        )

    @staticmethod
    def _run_select() -> str:
        return """
            SELECT run_id, run_kind, status, data_mode, deployment_stage,
                   started_at, finished_at, failure_reason, code_version,
                   environment_fingerprint
            FROM governance.run_records
        """

    @classmethod
    def _get_run(cls, connection: Connection, run_id: str) -> RunRecord | None:
        row = connection.execute(cls._run_select() + " WHERE run_id = %s", (run_id,)).fetchone()
        return None if row is None else cls._run_from_row(row)

    @staticmethod
    def _run_row(value: RunRecord) -> tuple[object, ...]:
        return (
            value.run_id,
            value.run_kind,
            value.status.value,
            value.context.data_mode.value,
            value.context.deployment_stage.value,
            value.created_at,
            value.finished_at,
            value.failure_reason,
            value.code_version,
            value.environment_fingerprint,
        )

    @staticmethod
    def _run_from_row(row: tuple[object, ...]) -> RunRecord:
        return RunRecord(
            run_id=str(row[0]),
            run_kind=str(row[1]),
            status=RunStatus(str(row[2])),
            context=RunContext(DataMode(str(row[3])), DeploymentStage(str(row[4]))),
            created_at=cast(datetime, row[5]),
            finished_at=cast(datetime | None, row[6]),
            failure_reason=None if row[7] is None else str(row[7]),
            code_version=str(row[8]),
            environment_fingerprint=str(row[9]),
        )

    @staticmethod
    def _artifact_select() -> str:
        return """
            SELECT artifact_id, content_hash, media_type, storage_uri, created_at, run_id
            FROM governance.artifacts
        """

    @classmethod
    def _get_artifact(cls, connection: Connection, artifact_id: str) -> Artifact | None:
        row = connection.execute(
            cls._artifact_select() + " WHERE artifact_id = %s",
            (artifact_id,),
        ).fetchone()
        return None if row is None else cls._artifact_from_row(row)

    @classmethod
    def _artifact_for_hash(cls, connection: Connection, content_hash: str) -> Artifact | None:
        row = connection.execute(
            cls._artifact_select() + " WHERE content_hash = %s",
            (content_hash,),
        ).fetchone()
        return None if row is None else cls._artifact_from_row(row)

    @staticmethod
    def _artifact_row(value: Artifact) -> tuple[object, ...]:
        return (
            value.artifact_id,
            value.content_hash,
            value.media_type,
            value.storage_uri,
            value.created_at,
            value.run_id,
        )

    @staticmethod
    def _artifact_from_row(row: tuple[object, ...]) -> Artifact:
        return Artifact(
            artifact_id=str(row[0]),
            content_hash=str(row[1]),
            media_type=str(row[2]),
            storage_uri=str(row[3]),
            created_at=cast(datetime, row[4]),
            run_id=str(row[5]),
        )

    @staticmethod
    def _require_identifier(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be empty")

    @staticmethod
    def _unavailable() -> GovernanceStoreUnavailable:
        return GovernanceStoreUnavailable("PostgreSQL governance store is unavailable")


__all__ = ["PostgresGovernanceRepository"]
