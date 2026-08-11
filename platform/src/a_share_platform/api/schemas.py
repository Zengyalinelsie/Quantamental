"""Pydantic response contracts for the read-only P1 API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from a_share_platform.domain.experiments import (
    ExperimentArtifact,
    ExperimentEnvironment,
    ExperimentFailure,
    ExperimentMetric,
    ExperimentParameter,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
    ExperimentTimeSplit,
    FeatureVersionBinding,
    LabelVersionBinding,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext


class ResponseContext(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    as_of: datetime
    system_as_of: datetime
    data_mode: DataMode
    deployment_stage: DeploymentStage
    trust_state: str | None = None
    dataset_version_ids: list[str] = Field(default_factory=list)
    model_version_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    data: Any
    context: ResponseContext


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunContextInput(StrictInput):
    data_mode: DataMode
    deployment_stage: DeploymentStage

    def to_domain(self) -> RunContext:
        return RunContext(self.data_mode, self.deployment_stage)


class ExperimentParameterInput(StrictInput):
    name: str
    value: str

    def to_domain(self) -> ExperimentParameter:
        return ExperimentParameter(self.name, self.value)


class FeatureVersionBindingInput(StrictInput):
    feature_id: str
    version: str
    definition_hash: str

    def to_domain(self) -> FeatureVersionBinding:
        return FeatureVersionBinding(self.feature_id, self.version, self.definition_hash)


class LabelVersionBindingInput(StrictInput):
    label_id: str
    version: str
    schema_hash: str
    dataset_version_id: str

    def to_domain(self) -> LabelVersionBinding:
        return LabelVersionBinding(
            self.label_id,
            self.version,
            self.schema_hash,
            self.dataset_version_id,
        )


class ExperimentTimeSplitInput(StrictInput):
    train_start: date
    train_end_exclusive: date
    validation_start: date
    validation_end_exclusive: date
    test_start: date
    test_end_exclusive: date
    version: str

    def to_domain(self) -> ExperimentTimeSplit:
        return ExperimentTimeSplit(
            train_start=self.train_start,
            train_end_exclusive=self.train_end_exclusive,
            validation_start=self.validation_start,
            validation_end_exclusive=self.validation_end_exclusive,
            test_start=self.test_start,
            test_end_exclusive=self.test_end_exclusive,
            version=self.version,
        )


class ExperimentEnvironmentInput(StrictInput):
    environment_id: str
    python_version: str
    platform: str
    dependency_lock_hash: str

    def to_domain(self) -> ExperimentEnvironment:
        return ExperimentEnvironment(
            self.environment_id,
            self.python_version,
            self.platform,
            self.dependency_lock_hash,
        )


class ExperimentSpecInput(StrictInput):
    spec_id: str
    research_question: str
    run_context: RunContextInput
    decision_time_policy_version: str
    readiness_evidence_hash: str
    universe_version_id: str
    dataset_version_ids: tuple[str, ...]
    feature_bindings: tuple[FeatureVersionBindingInput, ...]
    label_bindings: tuple[LabelVersionBindingInput, ...]
    time_split: ExperimentTimeSplitInput
    code_sha: str
    parameters: tuple[ExperimentParameterInput, ...]
    random_seed: int
    environment: ExperimentEnvironmentInput
    metric_names: tuple[str, ...]

    def to_domain(self) -> ExperimentSpec:
        return ExperimentSpec(
            spec_id=self.spec_id,
            research_question=self.research_question,
            run_context=self.run_context.to_domain(),
            decision_time_policy_version=self.decision_time_policy_version,
            readiness_evidence_hash=self.readiness_evidence_hash,
            universe_version_id=self.universe_version_id,
            dataset_version_ids=self.dataset_version_ids,
            feature_bindings=tuple(value.to_domain() for value in self.feature_bindings),
            label_bindings=tuple(value.to_domain() for value in self.label_bindings),
            time_split=self.time_split.to_domain(),
            code_sha=self.code_sha,
            parameters=tuple(value.to_domain() for value in self.parameters),
            random_seed=self.random_seed,
            environment=self.environment.to_domain(),
            metric_names=self.metric_names,
        )


class ExperimentMetricInput(StrictInput):
    name: str
    version: str
    value: Decimal
    unit: str

    def to_domain(self) -> ExperimentMetric:
        return ExperimentMetric(self.name, self.version, self.value, self.unit)


class ExperimentArtifactInput(StrictInput):
    artifact_id: str
    kind: str
    media_type: str
    content_hash: str

    def to_domain(self) -> ExperimentArtifact:
        return ExperimentArtifact(
            self.artifact_id,
            self.kind,
            self.media_type,
            self.content_hash,
        )


class ExperimentFailureInput(StrictInput):
    stage: str
    error_type: str
    message: str
    occurred_at: datetime
    retryable: bool

    def to_domain(self) -> ExperimentFailure:
        return ExperimentFailure(
            self.stage,
            self.error_type,
            self.message,
            self.occurred_at,
            self.retryable,
        )


class ExperimentRunInput(StrictInput):
    run_id: str
    spec: ExperimentSpecInput
    status: ExperimentRunStatus
    started_at: datetime | None
    finished_at: datetime | None
    metrics: tuple[ExperimentMetricInput, ...]
    artifacts: tuple[ExperimentArtifactInput, ...]
    failure: ExperimentFailureInput | None

    def to_domain(self) -> ExperimentRun:
        return ExperimentRun(
            run_id=self.run_id,
            spec=self.spec.to_domain(),
            status=self.status,
            started_at=self.started_at,
            finished_at=self.finished_at,
            metrics=tuple(value.to_domain() for value in self.metrics),
            artifacts=tuple(value.to_domain() for value in self.artifacts),
            failure=None if self.failure is None else self.failure.to_domain(),
        )
