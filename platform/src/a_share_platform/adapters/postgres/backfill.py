"""PostgreSQL ledger for backfill jobs, checkpoints, quality, and coverage."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol, cast

from a_share_platform.domain.backfill import (
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    BackfillDataDomain,
    BackfillJob,
    BackfillJobStatus,
    BackfillPlan,
    BackfillQualification,
    BackfillScope,
    BackfillScopeKind,
    DatasetCoverageReport,
    DatasetQualityReport,
    ProviderRetrievalMetadata,
    UniverseObservationMode,
)
from a_share_platform.domain.market_data import PriceAdjustment
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import ProviderUse


def _json_parameter(value: object) -> object:
    """Use psycopg's JSON adapter when installed; keep domain tests dependency-light."""

    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


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


class PostgresBackfillRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def save_job(self, value: BackfillJob) -> BackfillJob:
        self._connection.execute(
            """
            WITH inserted AS (
                INSERT INTO governance.ingestion_jobs (
                    job_id, plan_id, provider_id, status, plan, qualification,
                    output_trust_state, adjustment_mode, start_date, end_date,
                    created_at, updated_at, dataset_version_id, failure_reasons
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (job_id) DO NOTHING
                RETURNING job_id
            )
            INSERT INTO governance.ingestion_job_events (
                job_id, status, recorded_at, failure_reasons, dataset_version_id
            )
            SELECT %s, %s, %s, %s, %s FROM inserted
            """,
            (
                value.job_id,
                value.plan.plan_id,
                value.plan.provider_id,
                value.status.value,
                _json_parameter(self._plan_json(value.plan)),
                _json_parameter(self._qualification_json(value.qualification)),
                value.plan.output_trust_state.value,
                value.plan.price_adjustment.value,
                value.plan.start_date,
                value.plan.end_date,
                value.created_at,
                value.updated_at,
                value.dataset_version_id,
                _json_parameter(list(value.failure_reason)),
                value.job_id,
                value.status.value,
                value.updated_at,
                _json_parameter(list(value.failure_reason)),
                value.dataset_version_id,
            ),
        )
        return value

    def append_job_state(self, value: BackfillJob) -> BackfillJob:
        self._connection.execute(
            """
            WITH updated AS (
                UPDATE governance.ingestion_jobs
                SET status = %s, updated_at = %s, dataset_version_id = %s,
                    failure_reasons = %s
                WHERE job_id = %s
                RETURNING job_id
            )
            INSERT INTO governance.ingestion_job_events (
                job_id, status, recorded_at, failure_reasons, dataset_version_id
            )
            SELECT job_id, %s, %s, %s, %s FROM updated
            """,
            (
                value.status.value,
                value.updated_at,
                value.dataset_version_id,
                _json_parameter(list(value.failure_reason)),
                value.job_id,
                value.status.value,
                value.updated_at,
                _json_parameter(list(value.failure_reason)),
                value.dataset_version_id,
            ),
        )
        return value

    def get_job(self, job_id: str) -> BackfillJob | None:
        row = self._connection.execute(
            """
            SELECT job_id, plan, qualification, status, created_at, updated_at,
                   dataset_version_id, failure_reasons
            FROM governance.ingestion_jobs WHERE job_id = %s
            """,
            (job_id,),
        ).fetchone()
        return None if row is None else self._job_from_row(row)

    def list_jobs(self) -> tuple[BackfillJob, ...]:
        rows = self._connection.execute(
            """
            SELECT job_id, plan, qualification, status, created_at, updated_at,
                   dataset_version_id, failure_reasons
            FROM governance.ingestion_jobs ORDER BY created_at, job_id
            """
        ).fetchall()
        return tuple(self._job_from_row(row) for row in rows)

    def save_checkpoint(self, value: BackfillCheckpoint) -> BackfillCheckpoint:
        metadata = value.retrieval_metadata
        self._connection.execute(
            """
            INSERT INTO governance.ingestion_checkpoints (
                job_id, checkpoint_key, scope_id, data_domain, market,
                start_date, end_date, status, cursor, processed_rows, rejected_rows,
                content_hash, provider_id, provider_cutoff_date, retrieved_at, adjustment_mode,
                units, warnings, error, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (job_id, checkpoint_key) DO UPDATE SET
                status = EXCLUDED.status,
                cursor = EXCLUDED.cursor,
                processed_rows = EXCLUDED.processed_rows,
                rejected_rows = EXCLUDED.rejected_rows,
                content_hash = EXCLUDED.content_hash,
                provider_id = EXCLUDED.provider_id,
                provider_cutoff_date = EXCLUDED.provider_cutoff_date,
                retrieved_at = EXCLUDED.retrieved_at,
                adjustment_mode = EXCLUDED.adjustment_mode,
                units = EXCLUDED.units,
                warnings = EXCLUDED.warnings,
                error = EXCLUDED.error,
                updated_at = EXCLUDED.updated_at
            WHERE ingestion_checkpoints.status <> 'succeeded'
            """,
            (
                value.job_id,
                value.checkpoint_key,
                value.scope_id,
                value.domain.value,
                value.market,
                value.start_date,
                value.end_date,
                value.status.value,
                value.cursor,
                value.processed_rows,
                value.rejected_rows,
                value.content_hash,
                None if metadata is None else metadata.provider_id,
                None if metadata is None else metadata.cutoff_date,
                None if metadata is None else metadata.retrieved_at,
                None if metadata is None else metadata.adjustment_mode,
                _json_parameter({} if metadata is None else dict(metadata.units)),
                _json_parameter([] if metadata is None else list(metadata.warnings)),
                value.error,
                value.updated_at,
            ),
        )
        return value

    def get_checkpoint(
        self,
        job_id: str,
        checkpoint_key: str,
    ) -> BackfillCheckpoint | None:
        row = self._connection.execute(
            self._checkpoint_select() + " WHERE job_id = %s AND checkpoint_key = %s",
            (job_id, checkpoint_key),
        ).fetchone()
        return None if row is None else self._checkpoint_from_row(row)

    def list_checkpoints(self, job_id: str) -> tuple[BackfillCheckpoint, ...]:
        rows = self._connection.execute(
            self._checkpoint_select() + " WHERE job_id = %s ORDER BY checkpoint_key",
            (job_id,),
        ).fetchall()
        return tuple(self._checkpoint_from_row(row) for row in rows)

    def save_quality_report(self, value: DatasetQualityReport) -> DatasetQualityReport:
        self._connection.execute(
            """
            INSERT INTO governance.dataset_quality_reports (
                quality_report_id, dataset_version_id, job_id, status,
                checks_passed, checks_failed, issue_counts, warnings, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (quality_report_id) DO NOTHING
            """,
            (
                value.report_id,
                value.dataset_version_id,
                value.job_id,
                value.status.value,
                value.checks_passed,
                value.checks_failed,
                _json_parameter(dict(value.issue_counts)),
                _json_parameter(list(value.warnings)),
                value.created_at,
            ),
        )
        return value

    def save_coverage_report(
        self,
        value: DatasetCoverageReport,
    ) -> DatasetCoverageReport:
        self._connection.execute(
            """
            INSERT INTO governance.dataset_coverage_reports (
                coverage_report_id, dataset_version_id, job_id, scope_id,
                data_domain, start_date, end_date, expected_rows, observed_rows,
                coverage_ratio, warnings, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (coverage_report_id) DO NOTHING
            """,
            (
                value.report_id,
                value.dataset_version_id,
                value.job_id,
                value.scope_id,
                value.domain.value,
                value.start_date,
                value.end_date,
                value.expected_rows,
                value.observed_rows,
                value.coverage_ratio,
                _json_parameter(list(value.warnings)),
                value.created_at,
            ),
        )
        return value

    @staticmethod
    def _checkpoint_select() -> str:
        return """
            SELECT job_id, checkpoint_key, scope_id, data_domain, market,
                   start_date, end_date, status, updated_at, processed_rows,
                   rejected_rows, content_hash, cursor, error,
                   provider_id, provider_cutoff_date, retrieved_at, adjustment_mode, units, warnings
            FROM governance.ingestion_checkpoints
        """

    @staticmethod
    def _plan_json(value: BackfillPlan) -> dict[str, object]:
        return {
            "plan_id": value.plan_id,
            "provider_id": value.provider_id,
            "scopes": [
                {
                    "scope_id": scope.scope_id,
                    "name": scope.name,
                    "kind": scope.kind.value,
                    "benchmark_code": scope.benchmark_code,
                    "symbols": list(scope.symbols),
                }
                for scope in value.scopes
            ],
            "domains": [domain.value for domain in value.domains],
            "start_date": value.start_date.isoformat(),
            "end_date": value.end_date.isoformat(),
            "created_at": value.created_at.isoformat(),
            "output_trust_state": value.output_trust_state.value,
            "price_adjustment": value.price_adjustment.value,
            "provider_use": value.provider_use.value,
            "symbols": list(value.symbols),
            "markets": list(value.markets),
            "all_a_share": value.all_a_share,
            "universe_observation_mode": value.universe_observation_mode.value,
        }

    @staticmethod
    def _qualification_json(value: BackfillQualification) -> dict[str, object]:
        return {
            "provider_id": value.provider_id,
            "permitted": value.permitted,
            "evaluated_at": value.evaluated_at.isoformat(),
            "blockers": list(value.blockers),
            "warnings": list(value.warnings),
        }

    @staticmethod
    def _plan_from_json(raw: object) -> BackfillPlan:
        value = cast(Mapping[str, object], raw)
        scopes_raw = cast(list[Mapping[str, object]], value["scopes"])
        return BackfillPlan(
            plan_id=str(value["plan_id"]),
            provider_id=str(value["provider_id"]),
            scopes=tuple(
                BackfillScope(
                    scope_id=str(scope["scope_id"]),
                    name=str(scope["name"]),
                    kind=BackfillScopeKind(str(scope["kind"])),
                    benchmark_code=(
                        None
                        if scope.get("benchmark_code") is None
                        else str(scope["benchmark_code"])
                    ),
                    symbols=tuple(
                        str(item)
                        for item in cast(list[object], scope.get("symbols", []))
                    ),
                )
                for scope in scopes_raw
            ),
            domains=tuple(
                BackfillDataDomain(str(item))
                for item in cast(list[object], value["domains"])
            ),
            start_date=date.fromisoformat(str(value["start_date"])),
            end_date=date.fromisoformat(str(value["end_date"])),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            output_trust_state=DataTrustState(str(value["output_trust_state"])),
            price_adjustment=PriceAdjustment(str(value["price_adjustment"])),
            provider_use=ProviderUse(
                str(value.get("provider_use", ProviderUse.RAW_BULK_PERSISTENCE.value))
            ),
            symbols=tuple(str(item) for item in cast(list[object], value.get("symbols", []))),
            markets=tuple(
                str(item)
                for item in cast(
                    list[object],
                    value.get("markets", ["XSHG", "XSHE", "XBSE"]),
                )
            ),
            all_a_share=bool(value.get("all_a_share", False)),
            universe_observation_mode=UniverseObservationMode(
                str(
                    value.get(
                        "universe_observation_mode",
                        UniverseObservationMode.CONTINUOUS_DAILY.value,
                    )
                )
            ),
        )

    @staticmethod
    def _qualification_from_json(raw: object) -> BackfillQualification:
        value = cast(Mapping[str, object], raw)
        return BackfillQualification(
            provider_id=str(value["provider_id"]),
            permitted=cast(bool, value["permitted"]),
            evaluated_at=datetime.fromisoformat(str(value["evaluated_at"])),
            blockers=tuple(str(item) for item in cast(list[object], value["blockers"])),
            warnings=tuple(str(item) for item in cast(list[object], value["warnings"])),
        )

    @classmethod
    def _job_from_row(cls, row: tuple[object, ...]) -> BackfillJob:
        return BackfillJob(
            job_id=str(row[0]),
            plan=cls._plan_from_json(row[1]),
            qualification=cls._qualification_from_json(row[2]),
            status=BackfillJobStatus(str(row[3])),
            created_at=cast(datetime, row[4]),
            updated_at=cast(datetime, row[5]),
            dataset_version_id=None if row[6] is None else str(row[6]),
            failure_reason=tuple(str(item) for item in cast(list[object], row[7])),
        )

    @staticmethod
    def _checkpoint_from_row(row: tuple[object, ...]) -> BackfillCheckpoint:
        metadata = None
        if row[16] is not None:
            metadata = ProviderRetrievalMetadata(
                provider_id=str(row[14]),
                retrieved_at=cast(datetime, row[16]),
                cutoff_date=cast(date | None, row[15]),
                adjustment_mode=str(row[17]),
                units=tuple(
                    (str(key), str(value))
                    for key, value in cast(Mapping[object, object], row[18]).items()
                ),
                warnings=tuple(str(item) for item in cast(list[object], row[19])),
            )
        return BackfillCheckpoint(
            job_id=str(row[0]),
            checkpoint_key=str(row[1]),
            scope_id=str(row[2]),
            domain=BackfillDataDomain(str(row[3])),
            market=None if row[4] is None else str(row[4]),
            start_date=cast(date, row[5]),
            end_date=cast(date, row[6]),
            status=BackfillCheckpointStatus(str(row[7])),
            updated_at=cast(datetime, row[8]),
            processed_rows=int(cast(int, row[9])),
            rejected_rows=int(cast(int, row[10])),
            content_hash=None if row[11] is None else str(row[11]),
            cursor=None if row[12] is None else str(row[12]),
            error=None if row[13] is None else str(row[13]),
            retrieval_metadata=metadata,
        )
