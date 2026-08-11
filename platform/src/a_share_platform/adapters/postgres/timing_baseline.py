"""PostgreSQL persistence for current CSI benchmark inputs and baseline lineage."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.domain.governance import (
    DatasetVersion,
    LineageEdge,
    RunRecord,
    RunStatus,
    VersionConflictError,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.timing import (
    BenchmarkCloseBatch,
    BenchmarkCloseObservation,
)


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class PostgresTimingBaselineStore:
    """Store immutable bar inputs beside their dataset, run, and lineage records."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._datasets = PostgresDatasetVersionRepository(connection)

    def has_universe_version(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> bool:
        row = self._connection.execute(
            """
            SELECT 1
            FROM canonical.universe_versions AS version
            JOIN canonical.universe_definitions AS definition
              ON definition.definition_id = version.definition_id
            WHERE version.universe_version_id = %s
              AND definition.benchmark_id = %s
              AND EXISTS (
                  SELECT 1
                  FROM canonical.universe_memberships AS membership
                  WHERE membership.universe_version_id = version.universe_version_id
                    AND membership.valid_from <= %s
                    AND (membership.valid_to IS NULL OR %s < membership.valid_to)
              )
            """,
            (
                universe_version_id,
                benchmark_id.removeprefix("index:"),
                effective_session,
                effective_session,
            ),
        ).fetchone()
        return row is not None

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: Mapping[str, object],
    ) -> DatasetVersion:
        return self._datasets.register_dataset(value, metadata=metadata)

    def save_benchmark_batch(
        self,
        dataset_version_id: str,
        batch: BenchmarkCloseBatch,
    ) -> None:
        for row in batch.rows:
            self._connection.execute(
                """
                INSERT INTO observation.timing_benchmark_bars (
                    benchmark_id, session_date, unadjusted_close, provider_id,
                    retrieved_at, adjustment_mode, trust_state, data_mode,
                    dataset_version_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (dataset_version_id, benchmark_id, session_date) DO NOTHING
                """,
                (
                    row.benchmark_id,
                    row.session_date,
                    str(row.unadjusted_close),
                    batch.provider_id,
                    batch.retrieved_at,
                    batch.adjustment_mode,
                    batch.trust_state.value,
                    batch.data_mode.value,
                    dataset_version_id,
                ),
            )
        stored = self._read_batch(dataset_version_id)
        if stored != batch:
            raise VersionConflictError(
                f"immutable timing benchmark batch conflict: {dataset_version_id}"
            )

    def register_run(self, value: RunRecord) -> RunRecord:
        self._connection.execute(
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
        row = self._connection.execute(
            """
            SELECT run_id, run_kind, status, data_mode, deployment_stage,
                   started_at, finished_at, failure_reason, code_version,
                   environment_fingerprint
            FROM governance.run_records WHERE run_id = %s
            """,
            (value.run_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("timing baseline run insert was not observable")
        stored = self._run_from_row(row)
        if stored != value:
            raise VersionConflictError(f"run identifier conflict: {value.run_id}")
        return stored

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

    def _read_batch(self, dataset_version_id: str) -> BenchmarkCloseBatch | None:
        rows = self._connection.execute(
            """
            SELECT benchmark_id, session_date, unadjusted_close, provider_id,
                   retrieved_at, adjustment_mode, trust_state, data_mode
            FROM observation.timing_benchmark_bars
            WHERE dataset_version_id = %s
            ORDER BY session_date
            """,
            (dataset_version_id,),
        ).fetchall()
        if not rows:
            return None
        first = rows[0]
        return BenchmarkCloseBatch(
            benchmark_id=str(first[0]),
            rows=tuple(
                BenchmarkCloseObservation(
                    benchmark_id=str(row[0]),
                    session_date=cast(date, row[1]),
                    unadjusted_close=Decimal(str(row[2])),
                )
                for row in rows
            ),
            provider_id=str(first[3]),
            retrieved_at=cast(datetime, first[4]),
            adjustment_mode=str(first[5]),
            trust_state=DataTrustState(str(first[6])),
            data_mode=DataMode(str(first[7])),
        )

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
