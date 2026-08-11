"""Provider-neutral immutable contracts for reproducible factor experiments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from .run_context import DataMode, DeploymentStage, RunContext

_CONTENT_HASH = re.compile(r"^[0-9a-f]{64}$")
_CODE_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _content_hash(value: str, field_name: str) -> str:
    _text(value, field_name)
    if _CONTENT_HASH.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _day(value: date, field_name: str) -> date:
    if type(value) is not date:
        raise TypeError(f"{field_name} must be a date")
    return value


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ExperimentParameter:
    name: str
    value: str

    def __post_init__(self) -> None:
        _text(self.name, "parameter name")
        _text(self.value, f"parameter[{self.name}]")


@dataclass(frozen=True)
class FeatureVersionBinding:
    feature_id: str
    version: str
    definition_hash: str

    def __post_init__(self) -> None:
        _text(self.feature_id, "feature_id")
        _text(self.version, "feature version")
        _content_hash(self.definition_hash, "feature definition_hash")


@dataclass(frozen=True)
class LabelVersionBinding:
    label_id: str
    version: str
    schema_hash: str
    dataset_version_id: str

    def __post_init__(self) -> None:
        _text(self.label_id, "label_id")
        _text(self.version, "label version")
        _content_hash(self.schema_hash, "label schema_hash")
        _text(self.dataset_version_id, "label dataset_version_id")


@dataclass(frozen=True)
class ExperimentEnvironment:
    environment_id: str
    python_version: str
    platform: str
    dependency_lock_hash: str

    def __post_init__(self) -> None:
        _text(self.environment_id, "environment_id")
        _text(self.python_version, "python_version")
        _text(self.platform, "platform")
        _content_hash(self.dependency_lock_hash, "dependency_lock_hash")


@dataclass(frozen=True)
class ExperimentTimeSplit:
    """One explicit half-open train/validation/test split."""

    train_start: date
    train_end_exclusive: date
    validation_start: date
    validation_end_exclusive: date
    test_start: date
    test_end_exclusive: date
    version: str

    def __post_init__(self) -> None:
        for name in (
            "train_start",
            "train_end_exclusive",
            "validation_start",
            "validation_end_exclusive",
            "test_start",
            "test_end_exclusive",
        ):
            _day(getattr(self, name), name)
        _text(self.version, "time split version")
        if self.train_end_exclusive <= self.train_start:
            raise ValueError("train interval must be non-empty")
        if self.validation_end_exclusive <= self.validation_start:
            raise ValueError("validation interval must be non-empty")
        if self.test_end_exclusive <= self.test_start:
            raise ValueError("test interval must be non-empty")
        if self.validation_start < self.train_end_exclusive:
            raise ValueError("train and validation intervals overlap")
        if self.test_start < self.validation_end_exclusive:
            raise ValueError("validation and test intervals overlap")

    def hash_payload(self) -> dict[str, str]:
        return {
            "train_start": self.train_start.isoformat(),
            "train_end_exclusive": self.train_end_exclusive.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end_exclusive": self.validation_end_exclusive.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end_exclusive": self.test_end_exclusive.isoformat(),
            "version": self.version,
        }


@dataclass(frozen=True)
class ExperimentSpec:
    spec_id: str
    research_question: str
    run_context: RunContext
    decision_time_policy_version: str
    readiness_evidence_hash: str
    universe_version_id: str
    dataset_version_ids: tuple[str, ...]
    feature_bindings: tuple[FeatureVersionBinding, ...]
    label_bindings: tuple[LabelVersionBinding, ...]
    time_split: ExperimentTimeSplit
    code_sha: str
    parameters: tuple[ExperimentParameter, ...]
    random_seed: int
    environment: ExperimentEnvironment
    metric_names: tuple[str, ...]
    historical_evidence_eligible: bool = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.spec_id, "spec_id")
        _text(self.research_question, "research_question")
        if not isinstance(self.run_context, RunContext):
            raise TypeError("run_context must be a RunContext")
        _text(self.decision_time_policy_version, "decision_time_policy_version")
        _content_hash(self.readiness_evidence_hash, "readiness_evidence_hash")
        _text(self.universe_version_id, "universe_version_id")

        datasets = tuple(sorted(self.dataset_version_ids))
        if not datasets:
            raise ValueError("dataset_version_ids must not be empty")
        for value in datasets:
            _text(value, "dataset_version_id")
        if len(datasets) != len(set(datasets)):
            raise ValueError("dataset_version_ids must be unique")
        object.__setattr__(self, "dataset_version_ids", datasets)

        features = tuple(self.feature_bindings)
        if not features:
            raise ValueError("feature_bindings must not be empty")
        if any(not isinstance(value, FeatureVersionBinding) for value in features):
            raise TypeError("feature_bindings must contain FeatureVersionBinding values")
        features = tuple(sorted(features, key=lambda value: (value.feature_id, value.version)))
        feature_keys = tuple((value.feature_id, value.version) for value in features)
        if len(feature_keys) != len(set(feature_keys)):
            raise ValueError("feature bindings must be unique")
        object.__setattr__(self, "feature_bindings", features)

        labels = tuple(self.label_bindings)
        if not labels:
            raise ValueError("label_bindings must not be empty")
        if any(not isinstance(value, LabelVersionBinding) for value in labels):
            raise TypeError("label_bindings must contain LabelVersionBinding values")
        labels = tuple(sorted(labels, key=lambda value: (value.label_id, value.version)))
        label_keys = tuple((value.label_id, value.version) for value in labels)
        if len(label_keys) != len(set(label_keys)):
            raise ValueError("label bindings must be unique")
        missing_label_datasets = tuple(
            sorted(
                {
                    value.dataset_version_id
                    for value in labels
                    if value.dataset_version_id not in datasets
                }
            )
        )
        if missing_label_datasets:
            raise ValueError(
                "label dataset_version_id must be present in dataset_version_ids: "
                + ", ".join(missing_label_datasets)
            )
        object.__setattr__(self, "label_bindings", labels)

        if not isinstance(self.time_split, ExperimentTimeSplit):
            raise TypeError("time_split must be an ExperimentTimeSplit")
        if not isinstance(self.code_sha, str) or _CODE_SHA.fullmatch(self.code_sha) is None:
            raise ValueError("code_sha must be a full lowercase Git SHA")

        parameters = tuple(self.parameters)
        if any(not isinstance(value, ExperimentParameter) for value in parameters):
            raise TypeError("parameters must contain ExperimentParameter values")
        parameters = tuple(sorted(parameters, key=lambda value: value.name))
        parameter_names = tuple(value.name for value in parameters)
        if len(parameter_names) != len(set(parameter_names)):
            raise ValueError("experiment parameter names must be unique")
        object.__setattr__(self, "parameters", parameters)

        if type(self.random_seed) is not int or self.random_seed < 0:
            raise ValueError("random_seed must be a non-negative integer")
        if not isinstance(self.environment, ExperimentEnvironment):
            raise TypeError("environment must be an ExperimentEnvironment")

        metrics = tuple(sorted(self.metric_names))
        if not metrics:
            raise ValueError("metric_names must not be empty")
        for value in metrics:
            _text(value, "metric name")
        if len(metrics) != len(set(metrics)):
            raise ValueError("metric_names must be unique")
        object.__setattr__(self, "metric_names", metrics)
        object.__setattr__(
            self,
            "historical_evidence_eligible",
            self.run_context.data_mode is DataMode.STRICT_HISTORICAL
            and self.run_context.deployment_stage is DeploymentStage.RESEARCH,
        )
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    def hash_payload(self) -> dict[str, object]:
        return {
            "spec_id": self.spec_id,
            "research_question": self.research_question,
            "run_context": {
                "data_mode": self.run_context.data_mode.value,
                "deployment_stage": self.run_context.deployment_stage.value,
            },
            "decision_time_policy_version": self.decision_time_policy_version,
            "readiness_evidence_hash": self.readiness_evidence_hash,
            "universe_version_id": self.universe_version_id,
            "dataset_version_ids": self.dataset_version_ids,
            "feature_bindings": [
                {
                    "feature_id": value.feature_id,
                    "version": value.version,
                    "definition_hash": value.definition_hash,
                }
                for value in self.feature_bindings
            ],
            "label_bindings": [
                {
                    "label_id": value.label_id,
                    "version": value.version,
                    "schema_hash": value.schema_hash,
                    "dataset_version_id": value.dataset_version_id,
                }
                for value in self.label_bindings
            ],
            "time_split": self.time_split.hash_payload(),
            "code_sha": self.code_sha,
            "parameters": [
                {"name": value.name, "value": value.value}
                for value in self.parameters
            ],
            "random_seed": self.random_seed,
            "environment": {
                "environment_id": self.environment.environment_id,
                "python_version": self.environment.python_version,
                "platform": self.environment.platform,
                "dependency_lock_hash": self.environment.dependency_lock_hash,
            },
            "metric_names": self.metric_names,
        }


class ExperimentRunStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class ExperimentMetric:
    name: str
    version: str
    value: Decimal
    unit: str

    def __post_init__(self) -> None:
        _text(self.name, "metric name")
        _text(self.version, "metric version")
        if not isinstance(self.value, Decimal):
            raise TypeError("metric value must be a Decimal")
        if not self.value.is_finite():
            raise ValueError("metric value must be finite")
        _text(self.unit, "metric unit")


@dataclass(frozen=True)
class ExperimentArtifact:
    artifact_id: str
    kind: str
    media_type: str
    content_hash: str

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_id")
        _text(self.kind, "artifact kind")
        _text(self.media_type, "artifact media_type")
        _content_hash(self.content_hash, "artifact content_hash")


@dataclass(frozen=True)
class ExperimentFailure:
    stage: str
    error_type: str
    message: str
    occurred_at: datetime
    retryable: bool

    def __post_init__(self) -> None:
        _text(self.stage, "failure stage")
        _text(self.error_type, "failure error_type")
        _text(self.message, "failure message")
        _aware(self.occurred_at, "failure occurred_at")
        if type(self.retryable) is not bool:
            raise TypeError("failure retryable must be a boolean")


@dataclass(frozen=True)
class ExperimentRun:
    run_id: str
    spec: ExperimentSpec
    status: ExperimentRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    metrics: tuple[ExperimentMetric, ...]
    artifacts: tuple[ExperimentArtifact, ...]
    failure: ExperimentFailure | None
    spec_hash: str = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.run_id, "run_id")
        if not isinstance(self.spec, ExperimentSpec):
            raise TypeError("spec must be an ExperimentSpec")
        status = ExperimentRunStatus(self.status)
        object.__setattr__(self, "status", status)
        if self.started_at is not None:
            _aware(self.started_at, "started_at")
        if self.finished_at is not None:
            _aware(self.finished_at, "finished_at")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("finished_at cannot precede started_at")

        metrics = tuple(self.metrics)
        if any(not isinstance(value, ExperimentMetric) for value in metrics):
            raise TypeError("metrics must contain ExperimentMetric values")
        metrics = tuple(sorted(metrics, key=lambda value: value.name))
        metric_names = tuple(value.name for value in metrics)
        if len(metric_names) != len(set(metric_names)):
            raise ValueError("experiment metric names must be unique")
        unknown_metrics = tuple(sorted(set(metric_names) - set(self.spec.metric_names)))
        if unknown_metrics:
            raise ValueError(
                "run metrics are outside the declared metric family: "
                + ", ".join(unknown_metrics)
            )
        object.__setattr__(self, "metrics", metrics)

        artifacts = tuple(self.artifacts)
        if any(not isinstance(value, ExperimentArtifact) for value in artifacts):
            raise TypeError("artifacts must contain ExperimentArtifact values")
        artifacts = tuple(sorted(artifacts, key=lambda value: value.artifact_id))
        artifact_ids = tuple(value.artifact_id for value in artifacts)
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("experiment artifact_ids must be unique")
        object.__setattr__(self, "artifacts", artifacts)

        self._validate_status(metric_names, artifacts)
        object.__setattr__(self, "spec_hash", self.spec.content_hash)
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    def _validate_status(
        self,
        metric_names: tuple[str, ...],
        artifacts: tuple[ExperimentArtifact, ...],
    ) -> None:
        if self.status is ExperimentRunStatus.PLANNED:
            if any(
                value is not None
                for value in (self.started_at, self.finished_at, self.failure)
            ) or metric_names or artifacts:
                raise ValueError("planned run cannot carry execution results")
            return
        if self.status is ExperimentRunStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None:
                raise ValueError("running run requires only started_at")
            if metric_names or artifacts or self.failure is not None:
                raise ValueError("running run cannot carry terminal results")
            return
        if self.started_at is None or self.finished_at is None:
            raise ValueError("terminal run requires started_at and finished_at")
        if self.status is ExperimentRunStatus.SUCCEEDED:
            if self.failure is not None:
                raise ValueError("succeeded run cannot carry a failure")
            if metric_names != self.spec.metric_names:
                raise ValueError("succeeded run requires the exact declared metric family")
            if not artifacts:
                raise ValueError("succeeded run requires at least one artifact")
            return
        if self.failure is None:
            raise ValueError("failed run requires immutable failure evidence")
        if not isinstance(self.failure, ExperimentFailure):
            raise TypeError("failed run requires immutable failure evidence")
        if not self.started_at <= self.failure.occurred_at <= self.finished_at:
            raise ValueError("failure occurred_at must fall within the run interval")

    def hash_payload(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "spec_hash": self.spec.content_hash,
            "status": self.status.value,
            "started_at": (
                None if self.started_at is None else _canonical_time(self.started_at)
            ),
            "finished_at": (
                None if self.finished_at is None else _canonical_time(self.finished_at)
            ),
            "metrics": [
                {
                    "name": value.name,
                    "version": value.version,
                    "value": str(value.value),
                    "unit": value.unit,
                }
                for value in self.metrics
            ],
            "artifacts": [
                {
                    "artifact_id": value.artifact_id,
                    "kind": value.kind,
                    "media_type": value.media_type,
                    "content_hash": value.content_hash,
                }
                for value in self.artifacts
            ],
            "failure": (
                None
                if self.failure is None
                else {
                    "stage": self.failure.stage,
                    "error_type": self.failure.error_type,
                    "message": self.failure.message,
                    "occurred_at": _canonical_time(self.failure.occurred_at),
                    "retryable": self.failure.retryable,
                }
            ),
        }


class ExperimentRunConflict(RuntimeError):
    """An immutable run identifier was reused with different content."""


@dataclass(frozen=True)
class ExperimentRunRegistry:
    """Small immutable append-only registry used by domain and adapter tests."""

    runs: tuple[ExperimentRun, ...] = ()

    def __post_init__(self) -> None:
        values = tuple(self.runs)
        if any(not isinstance(value, ExperimentRun) for value in values):
            raise TypeError("runs must contain ExperimentRun values")
        run_ids = tuple(value.run_id for value in values)
        if len(run_ids) != len(set(run_ids)):
            raise ValueError("experiment run_ids must be unique")
        object.__setattr__(self, "runs", values)

    def register(self, value: ExperimentRun) -> ExperimentRunRegistry:
        if not isinstance(value, ExperimentRun):
            raise TypeError("value must be an ExperimentRun")
        for existing in self.runs:
            if existing.run_id != value.run_id:
                continue
            if existing == value:
                return self
            raise ExperimentRunConflict(
                f"immutable experiment run conflict: {value.run_id}"
            )
        return ExperimentRunRegistry((*self.runs, value))

    @property
    def failed_runs(self) -> tuple[ExperimentRun, ...]:
        return tuple(
            value for value in self.runs if value.status is ExperimentRunStatus.FAILED
        )


__all__ = [
    "ExperimentArtifact",
    "ExperimentEnvironment",
    "ExperimentFailure",
    "ExperimentMetric",
    "ExperimentParameter",
    "ExperimentRun",
    "ExperimentRunConflict",
    "ExperimentRunRegistry",
    "ExperimentRunStatus",
    "ExperimentSpec",
    "ExperimentTimeSplit",
    "FeatureVersionBinding",
    "LabelVersionBinding",
]
