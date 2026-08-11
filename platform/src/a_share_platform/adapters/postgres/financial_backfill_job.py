"""PostgreSQL lifecycle ledger for aggregate P3.5 financial backfill jobs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime
from typing import Protocol, cast

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.application.financial_backfill_job import (
    FinancialBackfillJobRecord,
    FinancialCompletedWorkUnit,
)
from a_share_platform.domain.backfill import BackfillJobStatus, BackfillQualification
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillCohort,
    FinancialBackfillPlan,
    FinancialStatementSelection,
)
from a_share_platform.domain.governance import DatasetVersion, VersionConflictError
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return Jsonb(value)


def _json_value(value: object, label: str) -> Mapping[str, object]:
    if isinstance(value, str):
        value = json.loads(value)
    wrapped = getattr(value, "obj", None)
    if wrapped is not None:
        value = wrapped
    if not isinstance(value, dict):
        raise TypeError(f"stored {label} must be a JSON object")
    return cast(Mapping[str, object], value)


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"stored {label} must be a JSON array")
    return value


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


class PostgresFinancialBackfillJobRepository:
    """Persist immutable job inputs, state events, and aggregate manifests."""

    _JOB_SELECT = """
        SELECT job_id, plan_id, plan, qualification, status, created_at, updated_at,
               dataset_version_id, failure_reasons, provider_id, output_trust_state,
               adjustment_mode, start_date, end_date
        FROM governance.ingestion_jobs
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._datasets = PostgresDatasetVersionRepository(connection)

    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id must not be empty")
        row = self._connection.execute(
            self._JOB_SELECT + " WHERE job_id = %s",
            (job_id,),
        ).fetchone()
        return None if row is None else self._job_from_row(row)

    def create_job(
        self,
        value: FinancialBackfillJobRecord,
    ) -> FinancialBackfillJobRecord:
        if not isinstance(value, FinancialBackfillJobRecord):
            raise TypeError("value must be a FinancialBackfillJobRecord")
        plan_json = self.plan_json(value.plan)
        qualification_json = self.qualification_json(value.qualification)
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
                ON CONFLICT DO NOTHING
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
                _json_parameter(plan_json),
                _json_parameter(qualification_json),
                value.plan.output_trust_state.value,
                "not_applicable",
                min(value.plan.report_period_ends),
                max(value.plan.report_period_ends),
                value.created_at,
                value.updated_at,
                value.dataset_version_id,
                _json_parameter(list(value.failure_reasons)),
                value.job_id,
                value.status.value,
                value.updated_at,
                _json_parameter(list(value.failure_reasons)),
                value.dataset_version_id,
            ),
        )
        rows = self._connection.execute(
            self._JOB_SELECT + " WHERE job_id = %s OR plan_id = %s ORDER BY job_id",
            (value.job_id, value.plan.plan_id),
        ).fetchall()
        if len(rows) != 1:
            raise VersionConflictError("financial plan/job uniqueness conflict")
        row = rows[0]
        if str(row[0]) != value.job_id or str(row[1]) != value.plan.plan_id:
            raise VersionConflictError("financial plan is bound to another job identifier")
        stored = self._job_from_row(row)
        if stored != value:
            raise VersionConflictError(f"immutable financial job conflict: {value.job_id}")
        if _json_value(row[2], "financial plan") != plan_json:
            raise VersionConflictError("immutable financial plan JSON conflict")
        if _json_value(row[3], "financial qualification") != qualification_json:
            raise VersionConflictError("immutable financial qualification JSON conflict")
        return stored

    def append_job_state(
        self,
        value: FinancialBackfillJobRecord,
        *,
        expected_previous_status: BackfillJobStatus,
    ) -> FinancialBackfillJobRecord:
        if not isinstance(value, FinancialBackfillJobRecord):
            raise TypeError("value must be a FinancialBackfillJobRecord")
        previous = BackfillJobStatus(expected_previous_status)
        self._connection.execute(
            """
            WITH updated AS (
                UPDATE governance.ingestion_jobs
                SET status = %s, updated_at = %s, dataset_version_id = %s,
                    failure_reasons = %s
                WHERE job_id = %s AND status = %s
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
                _json_parameter(list(value.failure_reasons)),
                value.job_id,
                previous.value,
                value.status.value,
                value.updated_at,
                _json_parameter(list(value.failure_reasons)),
                value.dataset_version_id,
            ),
        )
        stored = self.get_job(value.job_id)
        if stored is None:
            raise RuntimeError("financial job state update was not observable")
        if stored != value:
            raise VersionConflictError(f"financial job transition conflict: {value.job_id}")
        return stored

    def list_completed_units(
        self,
        job_id: str,
    ) -> tuple[FinancialCompletedWorkUnit, ...]:
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("job_id must not be empty")
        rows = self._connection.execute(
            """
            SELECT checkpoints.checkpoint_key,
                   receipts.dataset_version_id,
                   datasets.content_hash,
                   receipts.observation_count,
                   checkpoints.updated_at
            FROM governance.ingestion_checkpoints AS checkpoints
            JOIN governance.financial_backfill_persist_receipts AS receipts
              ON receipts.job_id = checkpoints.job_id
             AND receipts.checkpoint_key = checkpoints.checkpoint_key
            JOIN governance.dataset_versions AS datasets
              ON datasets.dataset_version_id = receipts.dataset_version_id
            WHERE checkpoints.job_id = %s
              AND checkpoints.data_domain = 'financial_statement'
              AND checkpoints.status = 'succeeded'
            ORDER BY checkpoints.checkpoint_key
            """,
            (job_id,),
        ).fetchall()
        completed = tuple(
            FinancialCompletedWorkUnit(
                checkpoint_key=str(row[0]),
                dataset_version_id=str(row[1]),
                content_hash=str(row[2]),
                observation_count=int(cast(int, row[3])),
                completed_at=cast(datetime, row[4]),
            )
            for row in rows
        )
        keys = tuple(item.checkpoint_key for item in completed)
        if len(keys) != len(set(keys)):
            raise RuntimeError("duplicate completed financial checkpoint rows")
        return completed

    def register_aggregate_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: Mapping[str, object],
    ) -> DatasetVersion:
        return self._datasets.register_dataset(value, metadata=metadata)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    @staticmethod
    def plan_json(value: FinancialBackfillPlan) -> dict[str, object]:
        return {
            "allow_read_through_cache": value.allow_read_through_cache,
            "bulk_persistence_acknowledged": value.bulk_persistence_acknowledged,
            "cohort": value.cohort.value,
            "created_at": value.created_at.isoformat(),
            "data_mode": value.data_mode.value,
            "mapping_version_id": value.mapping_version_id,
            "output_trust_state": value.output_trust_state.value,
            "plan_id": value.plan_id,
            "predecessor_coverage_report_id": value.predecessor_coverage_report_id,
            "provider_id": value.provider_id,
            "provider_profile_version": value.provider_profile_version,
            "report_period_ends": [
                report_period.isoformat() for report_period in value.report_period_ends
            ],
            "statements": [
                {
                    "provider_table": statement.provider_table,
                    "statement_type": statement.statement_type.value,
                }
                for statement in value.statements
            ],
            "symbol_bucket_size": value.symbol_bucket_size,
            "symbols": list(value.symbols),
            "universe_version_id": value.universe_version_id,
        }

    @staticmethod
    def qualification_json(value: BackfillQualification) -> dict[str, object]:
        return {
            "blockers": list(value.blockers),
            "evaluated_at": value.evaluated_at.isoformat(),
            "permitted": value.permitted,
            "provider_id": value.provider_id,
            "warnings": list(value.warnings),
        }

    @staticmethod
    def _plan_from_json(raw: object) -> FinancialBackfillPlan:
        value = _json_value(raw, "financial plan")
        expected_fields = {
            "allow_read_through_cache",
            "bulk_persistence_acknowledged",
            "cohort",
            "created_at",
            "data_mode",
            "mapping_version_id",
            "output_trust_state",
            "plan_id",
            "predecessor_coverage_report_id",
            "provider_id",
            "provider_profile_version",
            "report_period_ends",
            "statements",
            "symbol_bucket_size",
            "symbols",
            "universe_version_id",
        }
        if set(value) != expected_fields:
            raise ValueError("stored financial plan fields do not match schema")
        statement_values = _list(value["statements"], "financial statements")
        statements: list[FinancialStatementSelection] = []
        for raw_statement in statement_values:
            if not isinstance(raw_statement, dict) or set(raw_statement) != {
                "provider_table",
                "statement_type",
            }:
                raise ValueError("stored financial statement selection is invalid")
            statements.append(
                FinancialStatementSelection(
                    statement_type=StatementType(str(raw_statement["statement_type"])),
                    provider_table=str(raw_statement["provider_table"]),
                )
            )
        predecessor = value["predecessor_coverage_report_id"]
        return FinancialBackfillPlan(
            plan_id=str(value["plan_id"]),
            provider_id=str(value["provider_id"]),
            provider_profile_version=str(value["provider_profile_version"]),
            cohort=FinancialBackfillCohort(str(value["cohort"])),
            universe_version_id=str(value["universe_version_id"]),
            mapping_version_id=str(value["mapping_version_id"]),
            statements=tuple(statements),
            report_period_ends=tuple(
                date.fromisoformat(str(item))
                for item in _list(value["report_period_ends"], "report periods")
            ),
            symbols=tuple(str(item) for item in _list(value["symbols"], "financial symbols")),
            symbol_bucket_size=cast(int, value["symbol_bucket_size"]),
            created_at=datetime.fromisoformat(str(value["created_at"])),
            data_mode=DataMode(str(value["data_mode"])),
            output_trust_state=DataTrustState(str(value["output_trust_state"])),
            allow_read_through_cache=cast(bool, value["allow_read_through_cache"]),
            bulk_persistence_acknowledged=cast(
                bool,
                value["bulk_persistence_acknowledged"],
            ),
            predecessor_coverage_report_id=(None if predecessor is None else str(predecessor)),
        )

    @staticmethod
    def _qualification_from_json(raw: object) -> BackfillQualification:
        value = _json_value(raw, "financial qualification")
        if set(value) != {
            "blockers",
            "evaluated_at",
            "permitted",
            "provider_id",
            "warnings",
        }:
            raise ValueError("stored financial qualification fields do not match schema")
        return BackfillQualification(
            provider_id=str(value["provider_id"]),
            permitted=cast(bool, value["permitted"]),
            evaluated_at=datetime.fromisoformat(str(value["evaluated_at"])),
            blockers=tuple(
                str(item) for item in _list(value["blockers"], "qualification blockers")
            ),
            warnings=tuple(
                str(item) for item in _list(value["warnings"], "qualification warnings")
            ),
        )

    @classmethod
    def _job_from_row(cls, row: tuple[object, ...]) -> FinancialBackfillJobRecord:
        if len(row) != 14:
            raise ValueError("stored financial job row has an invalid shape")
        plan = cls._plan_from_json(row[2])
        qualification = cls._qualification_from_json(row[3])
        if str(row[1]) != plan.plan_id:
            raise ValueError("stored financial job plan_id does not match plan JSON")
        if str(row[9]) != plan.provider_id:
            raise ValueError("stored financial job provider does not match plan JSON")
        if str(row[10]) != DataTrustState.NORMALIZED_CURRENT.value:
            raise ValueError("stored financial job must remain normalized_current")
        if str(row[11]) != "not_applicable":
            raise ValueError("stored financial job adjustment_mode must be not_applicable")
        if cast(date, row[12]) != min(plan.report_period_ends) or cast(date, row[13]) != max(
            plan.report_period_ends
        ):
            raise ValueError("stored financial job period bounds do not match plan JSON")
        failure_values = _list(row[8], "financial job failure reasons")
        return FinancialBackfillJobRecord(
            job_id=str(row[0]),
            plan=plan,
            qualification=qualification,
            status=BackfillJobStatus(str(row[4])),
            created_at=cast(datetime, row[5]),
            updated_at=cast(datetime, row[6]),
            dataset_version_id=None if row[7] is None else str(row[7]),
            failure_reasons=tuple(str(item) for item in failure_values),
        )


__all__ = ["PostgresFinancialBackfillJobRepository"]
