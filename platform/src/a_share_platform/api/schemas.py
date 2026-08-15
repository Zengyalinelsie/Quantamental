"""Pydantic response contracts for the read-only P1 API."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

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
from a_share_platform.domain.factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorLifecycleEvent,
    FactorLifecycleStatus,
    FactorVersion,
    PromotionBinding,
    ValidationCheck,
    ValidationCheckName,
    ValidationOutcome,
    ValidationReport,
    ValidationWaiver,
)
from a_share_platform.domain.pit import DataTrustState
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


class StrictResponse(BaseModel):
    """Fail-closed response contract for server-owned P5 projections."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)


IdentityRole = Literal[
    "viewer",
    "researcher",
    "data_operator",
    "reviewer",
    "portfolio_manager",
    "trader",
    "administrator",
    "agent",
]
IdentityPermission = Literal[
    "read_public",
    "read_artifact",
    "create_experiment",
    "manage_data",
    "approve_research",
    "approve_portfolio",
    "send_order",
    "administer",
]


class IdentityProjection(StrictResponse):
    subject_id: str
    roles: list[IdentityRole]
    permissions: list[IdentityPermission]


class IdentityEnvelope(StrictResponse):
    data: IdentityProjection
    context: ResponseContext


class ArtifactProducerContext(StrictResponse):
    data_mode: DataMode
    deployment_stage: DeploymentStage


class ArtifactMetadata(StrictResponse):
    artifact_id: str
    run_id: str
    content_hash: str
    media_type: str
    created_at: datetime
    producer_context: ArtifactProducerContext


class ArtifactMetadataEnvelope(StrictResponse):
    data: ArtifactMetadata
    context: ResponseContext


class ArtifactMetadataListEnvelope(StrictResponse):
    data: list[ArtifactMetadata]
    context: ResponseContext


class ResearchWorkspaceBlocker(StrictResponse):
    code: str
    reason: str
    affected_binding: str
    evidence_ids: list[str]


class ScreenProjectedValue(StrictResponse):
    raw: str
    display: str


class ScreenRankProjection(StrictResponse):
    value: int
    display: str


class ScreenNullableRankProjection(StrictResponse):
    value: int | None
    display: str | None
    unavailable_reason: str | None


class ScreenRankChangeProjection(ScreenNullableRankProjection):
    direction: Literal["up", "down", "flat", "unavailable"]


class ScreenSecurityIdentityProjection(StrictResponse):
    security_id: str
    symbol: str
    display_name: str
    exchange: str


class ScreenIndustryProjection(StrictResponse):
    code: str
    display_name: str


class ScreenUniverseProjection(StrictResponse):
    universe_version_id: str
    display_name: str
    universe_size: int


class ScreenRankingRowProjection(StrictResponse):
    snapshot_id: str
    security: ScreenSecurityIdentityProjection
    industry: ScreenIndustryProjection
    rank: ScreenRankProjection
    previous_rank: ScreenNullableRankProjection
    rank_change: ScreenRankChangeProjection
    score: ScreenProjectedValue
    expected_return: ScreenProjectedValue
    confidence: ScreenProjectedValue
    investment_view_id: str
    trust_state: Literal["normalized_current", "pit_verified"]
    content_hash: str
    selected: bool


class SelectedScreenSecurityProjection(StrictResponse):
    security_id: str
    snapshot_id: str
    display_name: str
    symbol: str
    industry: ScreenIndustryProjection


class IndustryPeerProjection(StrictResponse):
    security_id: str
    display_name: str
    symbol: str
    rank: ScreenRankProjection
    expected_return: ScreenProjectedValue
    snapshot_id: str


class ScreenRankingProjection(StrictResponse):
    screen_id: str
    universe: ScreenUniverseProjection
    decision_time: datetime
    data_cutoff: datetime
    data_mode: DataMode
    trust_state: Literal["normalized_current", "pit_verified"]
    approval_scope: ApprovalScope
    model_version_id: str
    factor_version_ids: list[str]
    dataset_version_ids: list[str]
    feature_version_ids: list[str]
    rows: list[ScreenRankingRowProjection]
    selected_security: SelectedScreenSecurityProjection | None
    industry_peers: list[IndustryPeerProjection]
    warnings: list[str]


class InvestmentSecurityProjection(StrictResponse):
    security_id: str
    symbol: str
    exchange: str
    display_name: str


class WaterfallVisualProjection(StrictResponse):
    start_percent: str
    width_percent: str
    direction: Literal["positive", "negative", "flat"]


InvestmentComponentName = Literal["quality", "valuation", "revision", "event"]
InvestmentComponentStatus = Literal[
    "quantified",
    "constrained",
    "unavailable",
    "not_applicable",
]


class InvestmentComponentProjection(StrictResponse):
    component: InvestmentComponentName
    label: str
    status: InvestmentComponentStatus
    contribution: ScreenProjectedValue | None
    reason: str
    evidence_ids: list[str]
    visual: WaterfallVisualProjection | None


class ResidualProjection(StrictResponse):
    status: InvestmentComponentStatus
    contribution: ScreenProjectedValue | None
    reason: str
    evidence_ids: list[str]
    visual: WaterfallVisualProjection | None


class ClosureProjection(StrictResponse):
    status: Literal["passed", "failed", "unavailable"]
    displayed_total: str | None
    tolerance: str
    difference: str | None
    checked_by: str


class ExpectedReturnDistributionProjection(StrictResponse):
    point: ScreenProjectedValue
    p10: ScreenProjectedValue
    p50: ScreenProjectedValue
    p90: ScreenProjectedValue
    downside: ScreenProjectedValue


class CatalystProjection(StrictResponse):
    catalyst_id: str
    summary: str
    horizon: str
    evidence_ids: list[str]


class InvalidatorProjection(StrictResponse):
    invalidator_id: str
    summary: str
    evidence_ids: list[str]


class InvestmentEvidenceProjection(StrictResponse):
    evidence_id: str
    title: str
    source_kind: str
    available_at: datetime
    version: str
    source_url: str | None


class InvestmentViewVersionsProjection(StrictResponse):
    dataset_version_ids: list[str]
    feature_version_ids: list[str]
    model_version_id: str
    run_id: str
    code_version: str
    environment_id: str
    content_hash: str
    artifact_id: str | None


class InvestmentViewProjection(StrictResponse):
    view_id: str
    security: InvestmentSecurityProjection
    decision_time: datetime
    horizon: str
    data_mode: DataMode
    trust_state: Literal["normalized_current", "pit_verified"]
    trust_reason: str
    distribution: ExpectedReturnDistributionProjection
    components: list[InvestmentComponentProjection]
    residual: ResidualProjection
    closure: ClosureProjection
    confidence: ScreenProjectedValue
    catalysts: list[CatalystProjection]
    invalidators: list[InvalidatorProjection]
    evidence: list[InvestmentEvidenceProjection]
    versions: InvestmentViewVersionsProjection
    warnings: list[str]


class AlphaModelProjection(StrictResponse):
    model_version_id: str
    code_version: str
    environment_id: str
    investment_view_id: str
    investment_view_hash: str


class AlphaApprovalProjection(StrictResponse):
    approval_id: str
    approval_hash: str
    scope: ApprovalScope
    decision: Literal["approved"]
    reviewer_id: str
    reviewer_role: Literal["reviewer", "administrator"]
    decided_at: datetime
    reason: str


class ApprovedAlphaFactorProjection(StrictResponse):
    factor_version_id: str
    factor_version_hash: str
    lifecycle_status: Literal["production"]
    review_id: str
    review_hash: str
    validation_report_id: str
    validation_report_hash: str
    scientific_gate_passed: Literal[True]
    approval: AlphaApprovalProjection


class AlphaModelReadinessContextProjection(StrictResponse):
    requested_scope: ApprovalScope
    data_mode: DataMode
    deployment_stage: DeploymentStage
    checked_at: datetime


class AlphaModelUnavailableProjection(AlphaModelReadinessContextProjection):
    status: Literal["unavailable"]
    blocked_reasons: list[ResearchWorkspaceBlocker]


class AlphaModelReadyProjection(AlphaModelReadinessContextProjection):
    status: Literal["ready"]
    model: AlphaModelProjection
    factors: list[ApprovedAlphaFactorProjection]


AlphaModelReadinessProjection = Annotated[
    AlphaModelReadyProjection | AlphaModelUnavailableProjection,
    Field(discriminator="status"),
]


class ResearchWorkspaceData(StrictResponse):
    status: Literal["ready", "partial", "unavailable"]
    blockers: list[ResearchWorkspaceBlocker]
    screen: ScreenRankingProjection | None
    investment_view: InvestmentViewProjection | None
    alpha_model: AlphaModelReadinessProjection


class ResearchWorkspaceResponseContext(StrictResponse):
    as_of: datetime
    system_as_of: datetime
    data_mode: DataMode
    deployment_stage: DeploymentStage
    trust_state: str | None = None
    dataset_version_ids: list[str] = Field(default_factory=list)
    model_version_ids: list[str] = Field(default_factory=list)
    run_id: str | None = None
    coverage: dict[str, JsonValue] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ResearchWorkspaceEnvelope(StrictResponse):
    data: ResearchWorkspaceData
    context: ResearchWorkspaceResponseContext


DeskSectionKeyLiteral = Literal[
    "data_health",
    "screen_shifts",
    "portfolio_tracking",
    "timing_shadow",
    "event_feed",
    "pending_tasks",
    "active_failures",
]


class DeskBlockerProjection(StrictResponse):
    code: str
    reason: str
    affected_binding: str
    evidence_ids: list[str] = Field(default_factory=list)


class DeskSectionProjection(StrictResponse):
    """One desk domain.

    ``status`` covers only what the server can know.  ``loading`` and ``error``
    belong to the request lifecycle and are resolved by the client.  ``empty``
    and ``unavailable`` stay distinct on purpose: empty means the capability
    works and holds no record, unavailable means the capability or its store is
    missing.
    """

    key: DeskSectionKeyLiteral
    status: Literal["ready", "partial", "empty", "unavailable"]
    title: str
    blockers: list[DeskBlockerProjection] = Field(default_factory=list)
    coverage: dict[str, JsonValue] = Field(default_factory=dict)
    payload: JsonValue | None = None


class DeskData(StrictResponse):
    sections: list[DeskSectionProjection]


class DeskEnvelope(StrictResponse):
    data: DeskData
    context: ResearchWorkspaceResponseContext


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


class FactorLifecycleEventInput(StrictInput):
    event_id: str
    from_status: FactorLifecycleStatus
    to_status: FactorLifecycleStatus
    actor_id: str
    actor_role: str
    occurred_at: datetime
    reason: str
    evidence_hashes: tuple[str, ...]

    def to_domain(self) -> FactorLifecycleEvent:
        return FactorLifecycleEvent(
            event_id=self.event_id,
            from_status=self.from_status,
            to_status=self.to_status,
            actor_id=self.actor_id,
            actor_role=self.actor_role,
            occurred_at=self.occurred_at,
            reason=self.reason,
            evidence_hashes=self.evidence_hashes,
        )


class PromotionBindingInput(StrictInput):
    validation_report_id: str
    validation_report_hash: str
    approval_id: str
    approval_hash: str
    scope: ApprovalScope
    bound_at: datetime

    def to_domain(self) -> PromotionBinding:
        return PromotionBinding(
            validation_report_id=self.validation_report_id,
            validation_report_hash=self.validation_report_hash,
            approval_id=self.approval_id,
            approval_hash=self.approval_hash,
            scope=self.scope,
            bound_at=self.bound_at,
        )


class FactorVersionInput(StrictInput):
    factor_version_id: str
    factor_id: str
    semantic_version: str
    definition_hash: str
    code_sha: str
    dataset_version_ids: tuple[str, ...]
    feature_version_ids: tuple[str, ...]
    model_version_ids: tuple[str, ...]
    created_by: str
    created_at: datetime
    status: FactorLifecycleStatus
    lifecycle_events: tuple[FactorLifecycleEventInput, ...]
    promotion_bindings: tuple[PromotionBindingInput, ...]

    def to_domain(self) -> FactorVersion:
        return FactorVersion(
            factor_version_id=self.factor_version_id,
            factor_id=self.factor_id,
            semantic_version=self.semantic_version,
            definition_hash=self.definition_hash,
            code_sha=self.code_sha,
            dataset_version_ids=self.dataset_version_ids,
            feature_version_ids=self.feature_version_ids,
            model_version_ids=self.model_version_ids,
            created_by=self.created_by,
            created_at=self.created_at,
            status=self.status,
            lifecycle_events=tuple(value.to_domain() for value in self.lifecycle_events),
            promotion_bindings=tuple(
                value.to_domain() for value in self.promotion_bindings
            ),
        )


class ValidationWaiverInput(StrictInput):
    actor_id: str
    actor_role: str
    waived_at: datetime
    reason: str
    evidence_hashes: tuple[str, ...]

    def to_domain(self) -> ValidationWaiver:
        return ValidationWaiver(
            actor_id=self.actor_id,
            actor_role=self.actor_role,
            waived_at=self.waived_at,
            reason=self.reason,
            evidence_hashes=self.evidence_hashes,
        )


class ValidationCheckInput(StrictInput):
    name: ValidationCheckName
    outcome: ValidationOutcome
    evidence_hashes: tuple[str, ...]
    detail: str
    waiver: ValidationWaiverInput | None = None

    def to_domain(self) -> ValidationCheck:
        return ValidationCheck(
            name=self.name,
            outcome=self.outcome,
            evidence_hashes=self.evidence_hashes,
            detail=self.detail,
            waiver=None if self.waiver is None else self.waiver.to_domain(),
        )


class ValidationReportInput(StrictInput):
    report_id: str
    report_version: str
    factor_version_id: str
    experiment_run_id: str
    dataset_version_ids: tuple[str, ...]
    code_sha: str
    artifact_hashes: tuple[str, ...]
    run_context: RunContextInput
    input_trust_state: DataTrustState
    checks: tuple[ValidationCheckInput, ...]
    created_at: datetime

    def to_domain(self) -> ValidationReport:
        return ValidationReport(
            report_id=self.report_id,
            report_version=self.report_version,
            factor_version_id=self.factor_version_id,
            experiment_run_id=self.experiment_run_id,
            dataset_version_ids=self.dataset_version_ids,
            code_sha=self.code_sha,
            artifact_hashes=self.artifact_hashes,
            run_context=self.run_context.to_domain(),
            input_trust_state=self.input_trust_state,
            checks=tuple(value.to_domain() for value in self.checks),
            created_at=self.created_at,
        )


class FactorReviewInput(StrictInput):
    approval_id: str
    factor_version: FactorVersionInput
    validation_report: ValidationReportInput
    scope: ApprovalScope
    decision: ApprovalDecision
    decided_at: datetime
    reason: str
    evidence_hashes: tuple[str, ...]
