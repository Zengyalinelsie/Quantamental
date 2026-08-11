"""PostgreSQL adapter for immutable ExperimentSpec and ExperimentRun records."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

import psycopg

from a_share_platform.domain.experiments import (
    ExperimentArtifact,
    ExperimentEnvironment,
    ExperimentFailure,
    ExperimentMetric,
    ExperimentParameter,
    ExperimentRun,
    ExperimentRunConflict,
    ExperimentRunStatus,
    ExperimentSpec,
    ExperimentTimeSplit,
    FeatureVersionBinding,
    LabelVersionBinding,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.experiments import ExperimentStoreUnavailable


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "obj"):
        return value.obj
    return value


def _mapping(value: object, field_name: str) -> Mapping[object, object]:
    parsed = _json_value(value)
    if not isinstance(parsed, Mapping):
        raise TypeError(f"stored {field_name} must be an object")
    return parsed


def _array(value: object, field_name: str) -> Sequence[object]:
    parsed = _json_value(value)
    if not isinstance(parsed, (list, tuple)):
        raise TypeError(f"stored {field_name} must be an array")
    return parsed


def _required(document: Mapping[object, object], name: str) -> object:
    if name not in document:
        raise ValueError(f"stored experiment document is missing {name}")
    return document[name]


def _datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO datetime") from error


def _date(value: object, field_name: str) -> date:
    if type(value) is date:
        return cast(date, value)
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO date") from error


def _metric_document(value: ExperimentMetric) -> dict[str, object]:
    return {
        "name": value.name,
        "version": value.version,
        "value": str(value.value),
        "unit": value.unit,
    }


def _artifact_document(value: ExperimentArtifact) -> dict[str, object]:
    return {
        "artifact_id": value.artifact_id,
        "kind": value.kind,
        "media_type": value.media_type,
        "content_hash": value.content_hash,
    }


def _failure_document(value: ExperimentFailure | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "stage": value.stage,
        "error_type": value.error_type,
        "message": value.message,
        "occurred_at": value.occurred_at.isoformat(),
        "retryable": value.retryable,
    }


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


class PostgresExperimentRunRepository:
    """One transaction per operation; DSNs are never retained or exposed."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresExperimentRunRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(append_only=True)"

    def save_run(self, value: ExperimentRun) -> ExperimentRun:
        if not isinstance(value, ExperimentRun):
            raise TypeError("value must be an ExperimentRun")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._get_run(connection, value.run_id)
                if existing is not None:
                    if existing != value:
                        raise ExperimentRunConflict(
                            f"immutable experiment run conflict: {value.run_id}"
                        )
                    return existing
                self._save_spec(connection, value.spec)
                run_row = self.to_run_row(value)
                connection.execute(
                    """
                    INSERT INTO experiment_runs (
                        run_id, content_hash, spec_hash, spec_id, status, started_at,
                        metrics, artifacts, finished_at, failure_evidence
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id) DO NOTHING
                    """,
                    tuple(
                        _json_parameter(item) if index in {6, 7, 9} and item is not None else item
                        for index, item in enumerate(run_row)
                    ),
                )
                stored = self._get_run(connection, value.run_id)
                if stored is None:
                    raise RuntimeError("experiment run insert was not observable")
                if stored != value:
                    raise ExperimentRunConflict(
                        f"immutable experiment run conflict: {value.run_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise ExperimentStoreUnavailable(
                "PostgreSQL experiment store is unavailable"
            ) from error
        except psycopg.errors.UniqueViolation as error:
            raise ExperimentRunConflict(
                f"immutable experiment content conflict: {value.run_id}"
            ) from error

    def get_run(self, run_id: str) -> ExperimentRun | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_run(connection, run_id)
        except psycopg.OperationalError as error:
            raise ExperimentStoreUnavailable(
                "PostgreSQL experiment store is unavailable"
            ) from error

    def list_runs(self) -> tuple[ExperimentRun, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    self._run_select() + " ORDER BY run_id"
                ).fetchall()
                values: list[ExperimentRun] = []
                specs: dict[str, ExperimentSpec] = {}
                for row in rows:
                    spec_id = str(row[3])
                    selected = specs.get(spec_id)
                    if selected is None:
                        selected = self._get_spec(connection, spec_id)
                        if selected is None:
                            raise ValueError(
                                f"stored experiment run references missing spec: {spec_id}"
                            )
                        specs[spec_id] = selected
                    values.append(self._run_from_row(row, selected))
                return tuple(values)
        except psycopg.OperationalError as error:
            raise ExperimentStoreUnavailable(
                "PostgreSQL experiment store is unavailable"
            ) from error

    def _save_spec(self, connection: Connection, value: ExperimentSpec) -> None:
        existing = self._get_spec(connection, value.spec_id)
        if existing is not None:
            if existing != value:
                raise ExperimentRunConflict(
                    f"immutable experiment spec conflict: {value.spec_id}"
                )
            return
        row = self.to_spec_row(value)
        connection.execute(
            """
            INSERT INTO experiment_specs (
                spec_id, content_hash, data_mode, deployment_stage,
                universe_version_id, spec_document
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (spec_id) DO NOTHING
            """,
            (*row[:-1], _json_parameter(row[-1])),
        )
        stored = self._get_spec(connection, value.spec_id)
        if stored is None:
            raise RuntimeError("experiment spec insert was not observable")
        if stored != value:
            raise ExperimentRunConflict(
                f"immutable experiment spec conflict: {value.spec_id}"
            )

    def _get_spec(self, connection: Connection, spec_id: str) -> ExperimentSpec | None:
        row = connection.execute(
            self._spec_select() + " WHERE spec_id = %s",
            (spec_id,),
        ).fetchone()
        return None if row is None else self._spec_from_row(row)

    def _get_run(self, connection: Connection, run_id: str) -> ExperimentRun | None:
        row = connection.execute(
            self._run_select() + " WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        spec_id = str(row[3])
        selected = self._get_spec(connection, spec_id)
        if selected is None:
            raise ValueError(f"stored experiment run references missing spec: {spec_id}")
        return self._run_from_row(row, selected)

    @staticmethod
    def _spec_select() -> str:
        return """
            SELECT spec_id, content_hash, data_mode, deployment_stage,
                   universe_version_id, spec_document
            FROM experiment_specs
        """

    @staticmethod
    def _run_select() -> str:
        return """
            SELECT run_id, content_hash, spec_hash, spec_id, status, started_at,
                   metrics, artifacts, finished_at, failure_evidence
            FROM experiment_runs
        """

    @staticmethod
    def to_spec_row(value: ExperimentSpec) -> tuple[object, ...]:
        return (
            value.spec_id,
            value.content_hash,
            value.run_context.data_mode.value,
            value.run_context.deployment_stage.value,
            value.universe_version_id,
            value.hash_payload(),
        )

    @staticmethod
    def to_run_row(value: ExperimentRun) -> tuple[object, ...]:
        return (
            value.run_id,
            value.content_hash,
            value.spec_hash,
            value.spec.spec_id,
            value.status.value,
            value.started_at,
            [_metric_document(item) for item in value.metrics],
            [_artifact_document(item) for item in value.artifacts],
            value.finished_at,
            _failure_document(value.failure),
        )

    @classmethod
    def _spec_from_row(cls, row: Sequence[object]) -> ExperimentSpec:
        document = _mapping(row[5], "spec_document")
        context_document = _mapping(
            _required(document, "run_context"),
            "spec_document.run_context",
        )
        split_document = _mapping(
            _required(document, "time_split"),
            "spec_document.time_split",
        )
        environment_document = _mapping(
            _required(document, "environment"),
            "spec_document.environment",
        )
        feature_documents = _array(
            _required(document, "feature_bindings"),
            "spec_document.feature_bindings",
        )
        label_documents = _array(
            _required(document, "label_bindings"),
            "spec_document.label_bindings",
        )
        parameter_documents = _array(
            _required(document, "parameters"),
            "spec_document.parameters",
        )
        value = ExperimentSpec(
            spec_id=str(_required(document, "spec_id")),
            research_question=str(_required(document, "research_question")),
            run_context=RunContext(
                DataMode(str(_required(context_document, "data_mode"))),
                DeploymentStage(str(_required(context_document, "deployment_stage"))),
            ),
            decision_time_policy_version=str(
                _required(document, "decision_time_policy_version")
            ),
            readiness_evidence_hash=str(
                _required(document, "readiness_evidence_hash")
            ),
            universe_version_id=str(_required(document, "universe_version_id")),
            dataset_version_ids=tuple(
                str(item)
                for item in _array(
                    _required(document, "dataset_version_ids"),
                    "spec_document.dataset_version_ids",
                )
            ),
            feature_bindings=tuple(
                cls._feature_from_document(item) for item in feature_documents
            ),
            label_bindings=tuple(
                cls._label_from_document(item) for item in label_documents
            ),
            time_split=ExperimentTimeSplit(
                train_start=_date(
                    _required(split_document, "train_start"), "time_split.train_start"
                ),
                train_end_exclusive=_date(
                    _required(split_document, "train_end_exclusive"),
                    "time_split.train_end_exclusive",
                ),
                validation_start=_date(
                    _required(split_document, "validation_start"),
                    "time_split.validation_start",
                ),
                validation_end_exclusive=_date(
                    _required(split_document, "validation_end_exclusive"),
                    "time_split.validation_end_exclusive",
                ),
                test_start=_date(
                    _required(split_document, "test_start"), "time_split.test_start"
                ),
                test_end_exclusive=_date(
                    _required(split_document, "test_end_exclusive"),
                    "time_split.test_end_exclusive",
                ),
                version=str(_required(split_document, "version")),
            ),
            code_sha=str(_required(document, "code_sha")),
            parameters=tuple(
                cls._parameter_from_document(item) for item in parameter_documents
            ),
            random_seed=int(cast(int, _required(document, "random_seed"))),
            environment=ExperimentEnvironment(
                environment_id=str(_required(environment_document, "environment_id")),
                python_version=str(_required(environment_document, "python_version")),
                platform=str(_required(environment_document, "platform")),
                dependency_lock_hash=str(
                    _required(environment_document, "dependency_lock_hash")
                ),
            ),
            metric_names=tuple(
                str(item)
                for item in _array(
                    _required(document, "metric_names"),
                    "spec_document.metric_names",
                )
            ),
        )
        if value.spec_id != str(row[0]) or value.content_hash != str(row[1]):
            raise ExperimentRunConflict(
                f"immutable experiment spec content conflict: {row[0]}"
            )
        if value.run_context.data_mode.value != str(row[2]):
            raise ExperimentRunConflict(f"experiment spec data mode conflict: {row[0]}")
        if value.run_context.deployment_stage.value != str(row[3]):
            raise ExperimentRunConflict(
                f"experiment spec deployment stage conflict: {row[0]}"
            )
        if value.universe_version_id != str(row[4]):
            raise ExperimentRunConflict(f"experiment spec universe conflict: {row[0]}")
        return value

    @classmethod
    def _run_from_row(
        cls,
        row: Sequence[object],
        selected_spec: ExperimentSpec,
    ) -> ExperimentRun:
        metrics = tuple(
            cls._metric_from_document(item)
            for item in _array(row[6], "experiment metrics")
        )
        artifacts = tuple(
            cls._artifact_from_document(item)
            for item in _array(row[7], "experiment artifacts")
        )
        failure = (
            None
            if row[9] is None
            else cls._failure_from_document(row[9])
        )
        value = ExperimentRun(
            run_id=str(row[0]),
            spec=selected_spec,
            status=ExperimentRunStatus(str(row[4])),
            started_at=None if row[5] is None else _datetime(row[5], "started_at"),
            finished_at=None if row[8] is None else _datetime(row[8], "finished_at"),
            metrics=metrics,
            artifacts=artifacts,
            failure=failure,
        )
        if value.content_hash != str(row[1]):
            raise ExperimentRunConflict(
                f"immutable experiment run content conflict: {value.run_id}"
            )
        if value.spec_hash != str(row[2]) or value.spec.spec_id != str(row[3]):
            raise ExperimentRunConflict(
                f"immutable experiment run spec conflict: {value.run_id}"
            )
        return value

    @staticmethod
    def _feature_from_document(value: object) -> FeatureVersionBinding:
        document = _mapping(value, "feature binding")
        return FeatureVersionBinding(
            feature_id=str(_required(document, "feature_id")),
            version=str(_required(document, "version")),
            definition_hash=str(_required(document, "definition_hash")),
        )

    @staticmethod
    def _label_from_document(value: object) -> LabelVersionBinding:
        document = _mapping(value, "label binding")
        return LabelVersionBinding(
            label_id=str(_required(document, "label_id")),
            version=str(_required(document, "version")),
            schema_hash=str(_required(document, "schema_hash")),
            dataset_version_id=str(_required(document, "dataset_version_id")),
        )

    @staticmethod
    def _parameter_from_document(value: object) -> ExperimentParameter:
        document = _mapping(value, "experiment parameter")
        return ExperimentParameter(
            name=str(_required(document, "name")),
            value=str(_required(document, "value")),
        )

    @staticmethod
    def _metric_from_document(value: object) -> ExperimentMetric:
        document = _mapping(value, "experiment metric")
        return ExperimentMetric(
            name=str(_required(document, "name")),
            version=str(_required(document, "version")),
            value=Decimal(str(_required(document, "value"))),
            unit=str(_required(document, "unit")),
        )

    @staticmethod
    def _artifact_from_document(value: object) -> ExperimentArtifact:
        document = _mapping(value, "experiment artifact")
        return ExperimentArtifact(
            artifact_id=str(_required(document, "artifact_id")),
            kind=str(_required(document, "kind")),
            media_type=str(_required(document, "media_type")),
            content_hash=str(_required(document, "content_hash")),
        )

    @staticmethod
    def _failure_from_document(value: object) -> ExperimentFailure:
        document = _mapping(value, "failure_evidence")
        retryable = _required(document, "retryable")
        if type(retryable) is not bool:
            raise TypeError("stored failure retryable must be a boolean")
        return ExperimentFailure(
            stage=str(_required(document, "stage")),
            error_type=str(_required(document, "error_type")),
            message=str(_required(document, "message")),
            occurred_at=_datetime(
                _required(document, "occurred_at"), "failure occurred_at"
            ),
            retryable=cast(bool, retryable),
        )


__all__ = ["PostgresExperimentRunRepository"]
