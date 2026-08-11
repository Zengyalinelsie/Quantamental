"""Provider-neutral ports for frozen experiment export and result import."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol

from a_share_platform.domain.experiments import ExperimentRun, ExperimentSpec

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _hash(value: str, field_name: str) -> str:
    _text(value, field_name)
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


class ExperimentExchangeError(RuntimeError):
    """An external research-engine exchange could not be trusted."""


class ExperimentEngineUnavailable(ExperimentExchangeError):
    """The selected optional research engine is not installed or configured."""


class RecorderImportError(ExperimentExchangeError, ValueError):
    """Recorder output did not satisfy its explicit import schema."""


@dataclass(frozen=True)
class FrozenExperimentExport:
    schema_version: str
    run_id: str
    manifest: bytes
    content_hash: str

    def __post_init__(self) -> None:
        _text(self.schema_version, "schema_version")
        _text(self.run_id, "run_id")
        if not isinstance(self.manifest, bytes) or not self.manifest:
            raise ValueError("manifest must be non-empty bytes")
        _hash(self.content_hash, "content_hash")
        if hashlib.sha256(self.manifest).hexdigest() != self.content_hash:
            raise ValueError("content_hash does not match the frozen manifest")


@dataclass(frozen=True)
class ExperimentExportReceipt:
    engine_id: str
    experiment_name: str
    recorder_id: str
    export_content_hash: str

    def __post_init__(self) -> None:
        _text(self.engine_id, "engine_id")
        _text(self.experiment_name, "experiment_name")
        _text(self.recorder_id, "recorder_id")
        _hash(self.export_content_hash, "export_content_hash")


@dataclass(frozen=True)
class RecorderMetricField:
    recorder_name: str
    metric_name: str
    version: str
    unit: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.recorder_name, "recorder metric name"),
            (self.metric_name, "metric_name"),
            (self.version, "metric version"),
            (self.unit, "metric unit"),
        ):
            _text(value, field_name)


@dataclass(frozen=True)
class RecorderArtifactField:
    object_name: str
    artifact_id: str
    kind: str
    media_type: str

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.object_name, "recorder object name"),
            (self.artifact_id, "artifact_id"),
            (self.kind, "artifact kind"),
            (self.media_type, "artifact media_type"),
        ):
            _text(value, field_name)


@dataclass(frozen=True)
class RecorderImportSchema:
    schema_version: str
    succeeded_status: str
    failed_status: str
    metric_fields: tuple[RecorderMetricField, ...]
    artifact_fields: tuple[RecorderArtifactField, ...]
    failure_object_name: str

    def __post_init__(self) -> None:
        _text(self.schema_version, "schema_version")
        success = _text(self.succeeded_status, "succeeded_status")
        failure = _text(self.failed_status, "failed_status")
        if success == failure:
            raise ValueError("succeeded_status and failed_status must differ")
        metrics = tuple(self.metric_fields)
        if not metrics:
            raise ValueError("metric_fields must not be empty")
        if any(not isinstance(value, RecorderMetricField) for value in metrics):
            raise TypeError("metric_fields must contain RecorderMetricField values")
        recorder_names = tuple(value.recorder_name for value in metrics)
        metric_names = tuple(value.metric_name for value in metrics)
        if len(recorder_names) != len(set(recorder_names)):
            raise ValueError("recorder metric names must be unique")
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("metric_names must be unique")
        object.__setattr__(self, "metric_fields", metrics)

        artifacts = tuple(self.artifact_fields)
        if not artifacts:
            raise ValueError("artifact_fields must not be empty")
        if any(not isinstance(value, RecorderArtifactField) for value in artifacts):
            raise TypeError("artifact_fields must contain RecorderArtifactField values")
        object_names = tuple(value.object_name for value in artifacts)
        artifact_ids = tuple(value.artifact_id for value in artifacts)
        if len(object_names) != len(set(object_names)):
            raise ValueError("recorder object names must be unique")
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact_ids must be unique")
        object.__setattr__(self, "artifact_fields", artifacts)
        failure_name = _text(self.failure_object_name, "failure_object_name")
        if failure_name in set(object_names):
            raise ValueError("failure_object_name must not overlap artifact object names")


@dataclass(frozen=True)
class RecorderImportRequest:
    run_id: str
    spec: ExperimentSpec
    experiment_name: str
    recorder_id: str
    schema: RecorderImportSchema

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        if not isinstance(self.spec, ExperimentSpec):
            raise TypeError("spec must be an ExperimentSpec")
        _text(self.experiment_name, "experiment_name")
        _text(self.recorder_id, "recorder_id")
        if not isinstance(self.schema, RecorderImportSchema):
            raise TypeError("schema must be a RecorderImportSchema")


class ExperimentExportAdapter(Protocol):
    def export(
        self,
        value: FrozenExperimentExport,
        *,
        experiment_name: str,
        recorder_name: str,
    ) -> ExperimentExportReceipt: ...


class ExperimentRecorderImportAdapter(Protocol):
    def import_run(self, request: RecorderImportRequest) -> ExperimentRun: ...


__all__ = [
    "ExperimentEngineUnavailable",
    "ExperimentExchangeError",
    "ExperimentExportAdapter",
    "ExperimentExportReceipt",
    "ExperimentRecorderImportAdapter",
    "FrozenExperimentExport",
    "RecorderArtifactField",
    "RecorderImportError",
    "RecorderImportRequest",
    "RecorderImportSchema",
    "RecorderMetricField",
]
