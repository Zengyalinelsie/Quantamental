"""Qlib export/Recorder import adapter behind provider-neutral ports."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast

from a_share_platform.domain.experiments import (
    ExperimentArtifact,
    ExperimentFailure,
    ExperimentMetric,
    ExperimentRun,
    ExperimentRunStatus,
)
from a_share_platform.ports.experiment_exchange import (
    ExperimentEngineUnavailable,
    ExperimentExportReceipt,
    FrozenExperimentExport,
    RecorderArtifactField,
    RecorderImportError,
    RecorderImportRequest,
    RecorderMetricField,
)

_ENGINE_ID = "qlib"
_MANIFEST_OBJECT = "a_share_frozen_lineage.json"
_IMPORT_SCHEMA = "a-share-platform.recorder-import.v1"
_FAILURE_FIELDS = frozenset(
    {"stage", "error_type", "message", "occurred_at", "retryable"}
)


class QlibRecorderRecord(Protocol):
    recorder_id: str
    status: str
    started_at: object
    finished_at: object
    metrics: Mapping[str, object]

    def load_object(self, name: str) -> object: ...


class QlibRecorderGateway(Protocol):
    def create_recorder(
        self,
        *,
        experiment_name: str,
        recorder_name: str,
        parameters: Mapping[str, str],
        objects: Mapping[str, bytes],
    ) -> str: ...

    def get_recorder(
        self,
        *,
        experiment_name: str,
        recorder_id: str,
    ) -> QlibRecorderRecord: ...


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecorderImportError(f"{field_name} must not be empty")
    return value


def _time(value: object, field_name: str) -> datetime:
    selected: datetime
    if isinstance(value, datetime):
        selected = value
    elif isinstance(value, str):
        try:
            selected = datetime.fromisoformat(value)
        except ValueError as error:
            raise RecorderImportError(f"{field_name} must be ISO-8601") from error
    else:
        raise RecorderImportError(f"{field_name} must be a datetime or ISO-8601 string")
    if selected.tzinfo is None or selected.utcoffset() is None:
        raise RecorderImportError(f"{field_name} must be timezone-aware")
    return selected


def _metric_value(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise RecorderImportError(f"{field_name} must be an explicit numeric value")
    try:
        selected = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise RecorderImportError(f"{field_name} is not numeric") from error
    if not selected.is_finite():
        raise RecorderImportError(f"{field_name} must be finite")
    return selected


class QlibExperimentAdapter:
    """Map frozen platform contracts to and from a Qlib Recorder gateway."""

    def __init__(self, gateway: QlibRecorderGateway) -> None:
        self._gateway = gateway

    @classmethod
    def from_runtime(
        cls,
        *,
        module_loader: Callable[[str], object] = importlib.import_module,
    ) -> QlibExperimentAdapter:
        try:
            workflow = module_loader("qlib.workflow")
        except (ImportError, ModuleNotFoundError) as error:
            raise ExperimentEngineUnavailable(
                "Qlib SDK is unavailable; install and configure it before using this adapter"
            ) from error
        runtime = getattr(workflow, "R", None)
        if runtime is None:
            raise ExperimentEngineUnavailable("Qlib workflow runtime R is unavailable")
        return cls(_QlibSdkGateway(runtime))

    def export(
        self,
        value: FrozenExperimentExport,
        *,
        experiment_name: str,
        recorder_name: str,
    ) -> ExperimentExportReceipt:
        if not isinstance(value, FrozenExperimentExport):
            raise TypeError("value must be a FrozenExperimentExport")
        _text(experiment_name, "experiment_name")
        _text(recorder_name, "recorder_name")
        recorder_id = self._gateway.create_recorder(
            experiment_name=experiment_name,
            recorder_name=recorder_name,
            parameters={
                "a_share_export_schema": value.schema_version,
                "a_share_export_hash": value.content_hash,
                "a_share_experiment_run_id": value.run_id,
            },
            objects={_MANIFEST_OBJECT: value.manifest},
        )
        return ExperimentExportReceipt(
            engine_id=_ENGINE_ID,
            experiment_name=experiment_name,
            recorder_id=recorder_id,
            export_content_hash=value.content_hash,
        )

    def import_run(self, request: RecorderImportRequest) -> ExperimentRun:
        if not isinstance(request, RecorderImportRequest):
            raise TypeError("request must be a RecorderImportRequest")
        self._validate_schema_against_spec(request)
        try:
            record = self._gateway.get_recorder(
                experiment_name=request.experiment_name,
                recorder_id=request.recorder_id,
            )
        except Exception as error:
            raise RecorderImportError("Qlib Recorder is unavailable") from error
        if record.recorder_id != request.recorder_id:
            raise RecorderImportError("Qlib returned another recorder_id")
        status = _text(record.status, "Recorder status")
        if status == request.schema.succeeded_status:
            return self._successful_run(request, record)
        if status == request.schema.failed_status:
            return self._failed_run(request, record)
        raise RecorderImportError(f"Recorder status is not declared by schema: {status}")

    @staticmethod
    def _validate_schema_against_spec(request: RecorderImportRequest) -> None:
        if request.schema.schema_version != _IMPORT_SCHEMA:
            raise RecorderImportError(
                f"unsupported Recorder import schema: {request.schema.schema_version}"
            )
        names = tuple(sorted(value.metric_name for value in request.schema.metric_fields))
        if names != request.spec.metric_names:
            raise RecorderImportError(
                "Recorder metric schema must exactly match ExperimentSpec.metric_names"
            )

    def _successful_run(
        self,
        request: RecorderImportRequest,
        record: QlibRecorderRecord,
    ) -> ExperimentRun:
        metrics = self._metrics(
            record.metrics,
            request.schema.metric_fields,
            require_all=True,
        )
        artifacts = []
        for field in request.schema.artifact_fields:
            artifact = self._artifact(record, field, required=True)
            if artifact is None:  # Defensive guard for third-party implementations.
                raise RecorderImportError(
                    f"Recorder artifact is missing: {field.object_name}"
                )
            artifacts.append(artifact)
        try:
            return ExperimentRun(
                run_id=request.run_id,
                spec=request.spec,
                status=ExperimentRunStatus.SUCCEEDED,
                started_at=_time(record.started_at, "Recorder started_at"),
                finished_at=_time(record.finished_at, "Recorder finished_at"),
                metrics=metrics,
                artifacts=tuple(artifacts),
                failure=None,
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, RecorderImportError):
                raise
            raise RecorderImportError(
                "successful Recorder output violates ExperimentRun"
            ) from error

    def _failed_run(
        self,
        request: RecorderImportRequest,
        record: QlibRecorderRecord,
    ) -> ExperimentRun:
        metrics = self._metrics(
            record.metrics,
            request.schema.metric_fields,
            require_all=False,
        )
        artifacts = []
        for field in request.schema.artifact_fields:
            artifact = self._artifact(record, field, required=False)
            if artifact is not None:
                artifacts.append(artifact)
        failure = self._failure(record, request.schema.failure_object_name)
        try:
            return ExperimentRun(
                run_id=request.run_id,
                spec=request.spec,
                status=ExperimentRunStatus.FAILED,
                started_at=_time(record.started_at, "Recorder started_at"),
                finished_at=_time(record.finished_at, "Recorder finished_at"),
                metrics=metrics,
                artifacts=tuple(artifacts),
                failure=failure,
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, RecorderImportError):
                raise
            raise RecorderImportError(
                "failed Recorder output violates ExperimentRun"
            ) from error

    @staticmethod
    def _metrics(
        values: Mapping[str, object],
        fields: tuple[RecorderMetricField, ...],
        *,
        require_all: bool,
    ) -> tuple[ExperimentMetric, ...]:
        if not isinstance(values, Mapping):
            raise RecorderImportError("Recorder metrics must be a mapping")
        if any(not isinstance(name, str) for name in values):
            raise RecorderImportError("Recorder metric names must be strings")
        expected = {field.recorder_name for field in fields}
        observed = set(values)
        if not observed.issubset(expected) or (require_all and observed != expected):
            raise RecorderImportError(
                "Recorder metric schema mismatch: "
                f"expected={sorted(expected)}, observed={sorted(observed)}"
            )
        by_name = {field.recorder_name: field for field in fields}
        return tuple(
            ExperimentMetric(
                name=by_name[name].metric_name,
                version=by_name[name].version,
                value=_metric_value(values[name], f"Recorder metric {name}"),
                unit=by_name[name].unit,
            )
            for name in sorted(observed)
        )

    @staticmethod
    def _artifact(
        record: QlibRecorderRecord,
        field: RecorderArtifactField,
        *,
        required: bool,
    ) -> ExperimentArtifact | None:
        try:
            value = record.load_object(field.object_name)
        except KeyError as error:
            if not required:
                return None
            raise RecorderImportError(
                f"Recorder artifact is missing: {field.object_name}"
            ) from error
        except Exception as error:
            raise RecorderImportError(
                f"Recorder artifact could not be read: {field.object_name}"
            ) from error
        if not isinstance(value, bytes):
            raise RecorderImportError(
                f"Recorder artifact must be immutable bytes: {field.object_name}"
            )
        return ExperimentArtifact(
            artifact_id=field.artifact_id,
            kind=field.kind,
            media_type=field.media_type,
            content_hash=hashlib.sha256(value).hexdigest(),
        )

    @staticmethod
    def _failure(record: QlibRecorderRecord, object_name: str) -> ExperimentFailure:
        try:
            value = record.load_object(object_name)
        except Exception as error:
            raise RecorderImportError("failed Recorder is missing failure evidence") from error
        if not isinstance(value, bytes):
            raise RecorderImportError("Recorder failure evidence must be immutable JSON bytes")
        try:
            document = json.loads(value)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RecorderImportError("Recorder failure evidence is not valid JSON") from error
        if not isinstance(document, dict) or set(document) != _FAILURE_FIELDS:
            raise RecorderImportError(
                "Recorder failure evidence must contain exactly the declared fields"
            )
        retryable = document["retryable"]
        if type(retryable) is not bool:
            raise RecorderImportError("Recorder failure retryable must be a boolean")
        return ExperimentFailure(
            stage=_text(cast(str, document["stage"]), "failure stage"),
            error_type=_text(cast(str, document["error_type"]), "failure error_type"),
            message=_text(cast(str, document["message"]), "failure message"),
            occurred_at=_time(document["occurred_at"], "failure occurred_at"),
            retryable=retryable,
        )


class _QlibSdkRecorderRecord:
    def __init__(self, recorder: Any) -> None:
        self._recorder = recorder
        info = recorder.info
        self.recorder_id = str(info.id)
        self.status = str(info.status)
        self.started_at = info.start_time
        self.finished_at = info.end_time
        metrics = recorder.list_metrics()
        if not isinstance(metrics, Mapping):
            raise RecorderImportError("Qlib list_metrics did not return a mapping")
        self.metrics = cast(Mapping[str, object], metrics)

    def load_object(self, name: str) -> object:
        return self._recorder.load_object(name)


class _QlibSdkGateway:
    """Thin dynamic SDK wrapper so importing platform core never requires Qlib."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def create_recorder(
        self,
        *,
        experiment_name: str,
        recorder_name: str,
        parameters: Mapping[str, str],
        objects: Mapping[str, bytes],
    ) -> str:
        with self._runtime.start(
            experiment_name=experiment_name,
            recorder_name=recorder_name,
        ):
            recorder = self._runtime.get_recorder()
            recorder.log_params(**dict(parameters))
            recorder.save_objects(**dict(objects))
            recorder_id = getattr(recorder, "id", None)
            if recorder_id is None:
                recorder_id = getattr(recorder.info, "id", None)
            if recorder_id is None:
                raise ExperimentEngineUnavailable(
                    "Qlib did not return a Recorder identifier"
                )
            return str(recorder_id)

    def get_recorder(
        self,
        *,
        experiment_name: str,
        recorder_id: str,
    ) -> QlibRecorderRecord:
        recorder = self._runtime.get_recorder(
            recorder_id=recorder_id,
            experiment_name=experiment_name,
        )
        return _QlibSdkRecorderRecord(recorder)


__all__ = [
    "QlibExperimentAdapter",
    "QlibRecorderGateway",
    "QlibRecorderRecord",
]
