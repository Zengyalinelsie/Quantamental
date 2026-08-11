"""Fail-closed validation, approval, and lifecycle contracts for factors.

These objects record scientific and governance evidence.  They do not grant
broker access, order authority, or establish that a factor is scientifically
valid merely because the software contract tests pass.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum

from .pit import DataTrustState
from .run_context import DataMode, DeploymentStage, RunContext

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CODE_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_FACTOR_REVIEW_ROLES = frozenset({"reviewer", "administrator"})


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _sha256(value: str, field_name: str) -> str:
    _text(value, field_name)
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _code_sha(value: str) -> str:
    if not isinstance(value, str) or _CODE_SHA.fullmatch(value) is None:
        raise ValueError("code_sha must be a full lowercase Git SHA")
    return value


def _hashes(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    selected = tuple(values)
    if not selected:
        raise ValueError(f"{field_name} must not be empty")
    for value in selected:
        _sha256(value, field_name)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{field_name} must be unique")
    return tuple(sorted(selected))


def _identifiers(
    values: tuple[str, ...],
    field_name: str,
    *,
    required: bool,
) -> tuple[str, ...]:
    selected = tuple(values)
    if required and not selected:
        raise ValueError(f"{field_name} must not be empty")
    for value in selected:
        _text(value, field_name)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{field_name} must be unique")
    return tuple(sorted(selected))


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ValidationOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WAIVED = "waived"


class ValidationCheckName(str, Enum):
    PIT_INPUT_QUALIFICATION = "pit_input_qualification"
    IC = "ic"
    RANK_IC = "rank_ic"
    HAC_OR_BLOCK_BOOTSTRAP = "hac_or_block_bootstrap"
    QUANTILE_MONOTONICITY = "quantile_monotonicity"
    DECAY_TURNOVER_COVERAGE = "decay_turnover_coverage"
    INDUSTRY_SIZE_NEUTRALITY = "industry_size_neutrality"
    FAMA_MACBETH = "fama_macbeth"
    REGIME_SUBPERIOD_STABILITY = "regime_subperiod_stability"
    FDR = "fdr"
    WALK_FORWARD_OOS = "walk_forward_oos"
    COST_CAPACITY = "cost_capacity"


_NON_WAIVABLE_CHECKS = frozenset(
    {
        ValidationCheckName.PIT_INPUT_QUALIFICATION,
        ValidationCheckName.WALK_FORWARD_OOS,
    }
)


@dataclass(frozen=True)
class ValidationWaiver:
    actor_id: str
    actor_role: str
    waived_at: datetime
    reason: str
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.actor_id, "waiver actor_id")
        role = _text(self.actor_role, "waiver actor_role")
        if role not in _FACTOR_REVIEW_ROLES:
            raise PermissionError(
                "waiver actor_role must have human factor review authority"
            )
        _aware(self.waived_at, "waived_at")
        _text(self.reason, "waiver reason")
        object.__setattr__(
            self,
            "evidence_hashes",
            _hashes(self.evidence_hashes, "waiver evidence_hashes"),
        )


@dataclass(frozen=True)
class ValidationCheck:
    name: ValidationCheckName
    outcome: ValidationOutcome
    evidence_hashes: tuple[str, ...]
    detail: str
    waiver: ValidationWaiver | None = None

    def __post_init__(self) -> None:
        name = ValidationCheckName(self.name)
        outcome = ValidationOutcome(self.outcome)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(
            self,
            "evidence_hashes",
            _hashes(self.evidence_hashes, "validation check evidence_hashes"),
        )
        _text(self.detail, "validation check detail")
        if outcome is ValidationOutcome.WAIVED:
            if name in _NON_WAIVABLE_CHECKS:
                raise ValueError(f"{name.value} is a non-waivable hard gate")
            if not isinstance(self.waiver, ValidationWaiver):
                raise ValueError("waived validation check requires a waiver record")
        elif self.waiver is not None:
            raise ValueError("waiver is only valid for a waived validation check")

    def hash_payload(self) -> dict[str, object]:
        waiver = self.waiver
        return {
            "name": self.name.value,
            "outcome": self.outcome.value,
            "evidence_hashes": self.evidence_hashes,
            "detail": self.detail,
            "waiver": None
            if waiver is None
            else {
                "actor_id": waiver.actor_id,
                "actor_role": waiver.actor_role,
                "waived_at": _canonical_time(waiver.waived_at),
                "reason": waiver.reason,
                "evidence_hashes": waiver.evidence_hashes,
            },
        }


@dataclass(frozen=True)
class ValidationReport:
    report_id: str
    report_version: str
    factor_version_id: str
    experiment_run_id: str
    dataset_version_ids: tuple[str, ...]
    code_sha: str
    artifact_hashes: tuple[str, ...]
    run_context: RunContext
    input_trust_state: DataTrustState
    checks: tuple[ValidationCheck, ...]
    created_at: datetime
    historical_evidence_eligible: bool = field(init=False)
    passes_promotion_gate: bool = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.report_id, "report_id"),
            (self.report_version, "report_version"),
            (self.factor_version_id, "factor_version_id"),
            (self.experiment_run_id, "experiment_run_id"),
        ):
            _text(value, field_name)
        object.__setattr__(
            self,
            "dataset_version_ids",
            _identifiers(
                self.dataset_version_ids,
                "dataset_version_ids",
                required=True,
            ),
        )
        _code_sha(self.code_sha)
        object.__setattr__(
            self,
            "artifact_hashes",
            _hashes(self.artifact_hashes, "artifact_hashes"),
        )
        if not isinstance(self.run_context, RunContext):
            raise TypeError("run_context must be a RunContext")
        trust_state = DataTrustState(self.input_trust_state)
        object.__setattr__(self, "input_trust_state", trust_state)
        created_at = _aware(self.created_at, "created_at")

        selected_checks = tuple(self.checks)
        if any(not isinstance(item, ValidationCheck) for item in selected_checks):
            raise TypeError("checks must contain ValidationCheck values")
        names = tuple(item.name for item in selected_checks)
        if len(names) != len(set(names)):
            raise ValueError("validation check names must be unique")
        missing = set(ValidationCheckName).difference(names)
        if missing:
            missing_names = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"missing validation checks: {missing_names}")
        selected_checks = tuple(sorted(selected_checks, key=lambda item: item.name.value))
        object.__setattr__(self, "checks", selected_checks)

        historical = (
            self.run_context.data_mode is DataMode.STRICT_HISTORICAL
            and self.run_context.deployment_stage is DeploymentStage.RESEARCH
            and trust_state is DataTrustState.PIT_VERIFIED
        )
        object.__setattr__(self, "historical_evidence_eligible", historical)
        hard_gates_pass = all(
            item.outcome is ValidationOutcome.PASS
            for item in selected_checks
            if item.name in _NON_WAIVABLE_CHECKS
        )
        no_failures = all(
            item.outcome is not ValidationOutcome.FAIL for item in selected_checks
        )
        object.__setattr__(
            self,
            "passes_promotion_gate",
            historical and hard_gates_pass and no_failures,
        )
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(
                {
                    "report_id": self.report_id,
                    "report_version": self.report_version,
                    "factor_version_id": self.factor_version_id,
                    "experiment_run_id": self.experiment_run_id,
                    "dataset_version_ids": self.dataset_version_ids,
                    "code_sha": self.code_sha,
                    "artifact_hashes": self.artifact_hashes,
                    "run_context": {
                        "data_mode": self.run_context.data_mode.value,
                        "deployment_stage": self.run_context.deployment_stage.value,
                    },
                    "input_trust_state": self.input_trust_state.value,
                    "checks": [item.hash_payload() for item in self.checks],
                    "created_at": _canonical_time(created_at),
                }
            ),
        )

    @property
    def failed_checks(self) -> tuple[ValidationCheck, ...]:
        return tuple(
            item for item in self.checks if item.outcome is ValidationOutcome.FAIL
        )


class ApprovalScope(str, Enum):
    RESEARCH_BACKTEST = "research_backtest"
    SHADOW = "shadow"
    PAPER = "paper"
    LIMITED_LIVE = "limited_live"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUEST_CHANGES = "request_changes"


@dataclass(frozen=True)
class PromotionApproval:
    approval_id: str
    factor_version_id: str
    validation_report_id: str
    validation_report_hash: str
    scope: ApprovalScope
    decision: ApprovalDecision
    actor_id: str
    actor_role: str
    decided_at: datetime
    reason: str
    evidence_hashes: tuple[str, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.approval_id, "approval_id"),
            (self.factor_version_id, "factor_version_id"),
            (self.validation_report_id, "validation_report_id"),
            (self.actor_id, "approval actor_id"),
            (self.reason, "approval reason"),
        ):
            _text(value, field_name)
        _sha256(self.validation_report_hash, "validation_report_hash")
        scope = ApprovalScope(self.scope)
        decision = ApprovalDecision(self.decision)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "decision", decision)
        role = _text(self.actor_role, "approval actor_role")
        if role not in _FACTOR_REVIEW_ROLES:
            raise PermissionError(
                "actor_role does not have factor promotion approval authority"
            )
        decided_at = _aware(self.decided_at, "decided_at")
        evidence_hashes = _hashes(self.evidence_hashes, "approval evidence_hashes")
        object.__setattr__(self, "evidence_hashes", evidence_hashes)
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(
                {
                    "approval_id": self.approval_id,
                    "factor_version_id": self.factor_version_id,
                    "validation_report_id": self.validation_report_id,
                    "validation_report_hash": self.validation_report_hash,
                    "scope": scope.value,
                    "decision": decision.value,
                    "actor_id": self.actor_id,
                    "actor_role": role,
                    "decided_at": _canonical_time(decided_at),
                    "reason": self.reason,
                    "evidence_hashes": evidence_hashes,
                }
            ),
        )

    @property
    def grants_account_access(self) -> bool:
        return False

    @property
    def grants_order_authority(self) -> bool:
        return False

    def authorizes(
        self,
        *,
        factor_version_id: str,
        validation_report: ValidationReport,
        scope: ApprovalScope | str,
    ) -> bool:
        if not isinstance(validation_report, ValidationReport):
            return False
        try:
            requested_scope = ApprovalScope(scope)
        except ValueError:
            return False
        return (
            self.decision is ApprovalDecision.APPROVED
            and self.factor_version_id == factor_version_id
            and self.validation_report_id == validation_report.report_id
            and self.validation_report_hash == validation_report.content_hash
            and self.scope is requested_scope
            and validation_report.factor_version_id == factor_version_id
            and validation_report.passes_promotion_gate
        )


class FactorLifecycleStatus(str, Enum):
    DRAFT = "draft"
    RESEARCH = "research"
    SHADOW = "shadow"
    CANDIDATE = "candidate"
    PRODUCTION = "production"
    SUSPENDED = "suspended"
    RETIRED = "retired"


_ALLOWED_TRANSITIONS = frozenset(
    {
        (FactorLifecycleStatus.DRAFT, FactorLifecycleStatus.RESEARCH),
        (FactorLifecycleStatus.RESEARCH, FactorLifecycleStatus.SHADOW),
        (FactorLifecycleStatus.SHADOW, FactorLifecycleStatus.CANDIDATE),
        (FactorLifecycleStatus.CANDIDATE, FactorLifecycleStatus.PRODUCTION),
        (FactorLifecycleStatus.PRODUCTION, FactorLifecycleStatus.SUSPENDED),
        (FactorLifecycleStatus.SUSPENDED, FactorLifecycleStatus.PRODUCTION),
        (FactorLifecycleStatus.SUSPENDED, FactorLifecycleStatus.RETIRED),
    }
)


class FactorPromotionError(RuntimeError):
    """A factor failed a validation, approval, or reproducibility gate."""


@dataclass(frozen=True)
class FactorLifecycleEvent:
    event_id: str
    from_status: FactorLifecycleStatus
    to_status: FactorLifecycleStatus
    actor_id: str
    actor_role: str
    occurred_at: datetime
    reason: str
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.event_id, "event_id")
        source = FactorLifecycleStatus(self.from_status)
        target = FactorLifecycleStatus(self.to_status)
        object.__setattr__(self, "from_status", source)
        object.__setattr__(self, "to_status", target)
        if (source, target) not in _ALLOWED_TRANSITIONS:
            raise ValueError(
                f"illegal factor lifecycle transition: {source.value} -> {target.value}"
            )
        _text(self.actor_id, "event actor_id")
        _text(self.actor_role, "event actor_role")
        _aware(self.occurred_at, "occurred_at")
        _text(self.reason, "event reason")
        object.__setattr__(
            self,
            "evidence_hashes",
            _hashes(self.evidence_hashes, "event evidence_hashes"),
        )


@dataclass(frozen=True)
class PromotionBinding:
    validation_report_id: str
    validation_report_hash: str
    approval_id: str
    approval_hash: str
    scope: ApprovalScope
    bound_at: datetime

    def __post_init__(self) -> None:
        _text(self.validation_report_id, "validation_report_id")
        _sha256(self.validation_report_hash, "validation_report_hash")
        _text(self.approval_id, "approval_id")
        _sha256(self.approval_hash, "approval_hash")
        object.__setattr__(self, "scope", ApprovalScope(self.scope))
        _aware(self.bound_at, "bound_at")


@dataclass(frozen=True)
class FactorVersion:
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
    status: FactorLifecycleStatus = FactorLifecycleStatus.DRAFT
    lifecycle_events: tuple[FactorLifecycleEvent, ...] = ()
    promotion_bindings: tuple[PromotionBinding, ...] = ()
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.factor_version_id, "factor_version_id"),
            (self.factor_id, "factor_id"),
            (self.semantic_version, "semantic_version"),
            (self.created_by, "created_by"),
        ):
            _text(value, field_name)
        _sha256(self.definition_hash, "definition_hash")
        _code_sha(self.code_sha)
        datasets = _identifiers(
            self.dataset_version_ids,
            "dataset_version_ids",
            required=True,
        )
        features = _identifiers(
            self.feature_version_ids,
            "feature_version_ids",
            required=True,
        )
        models = _identifiers(
            self.model_version_ids,
            "model_version_ids",
            required=False,
        )
        object.__setattr__(self, "dataset_version_ids", datasets)
        object.__setattr__(self, "feature_version_ids", features)
        object.__setattr__(self, "model_version_ids", models)
        created_at = _aware(self.created_at, "created_at")
        status = FactorLifecycleStatus(self.status)
        object.__setattr__(self, "status", status)

        events = tuple(self.lifecycle_events)
        if any(not isinstance(item, FactorLifecycleEvent) for item in events):
            raise TypeError("lifecycle_events must contain FactorLifecycleEvent values")
        if len({item.event_id for item in events}) != len(events):
            raise ValueError("lifecycle event identifiers must be unique")
        expected = FactorLifecycleStatus.DRAFT
        previous_time = created_at
        for item in events:
            if item.from_status is not expected:
                raise ValueError("lifecycle event history is not contiguous")
            if item.occurred_at < previous_time:
                raise ValueError("lifecycle events must be time ordered")
            expected = item.to_status
            previous_time = item.occurred_at
        if expected is not status:
            raise ValueError("lifecycle event history does not resolve to status")
        object.__setattr__(self, "lifecycle_events", events)

        bindings = tuple(self.promotion_bindings)
        if any(not isinstance(item, PromotionBinding) for item in bindings):
            raise TypeError("promotion_bindings must contain PromotionBinding values")
        if len({item.approval_id for item in bindings}) != len(bindings):
            raise ValueError("promotion approval identifiers must be unique")
        production_events = tuple(
            item
            for item in events
            if item.to_status is FactorLifecycleStatus.PRODUCTION
        )
        if len(production_events) != len(bindings) or any(
            item.occurred_at != binding.bound_at
            for item, binding in zip(production_events, bindings)
        ):
            raise ValueError(
                "each production transition must have one attached approval binding"
            )
        object.__setattr__(self, "promotion_bindings", bindings)

        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(
                {
                    "factor_version_id": self.factor_version_id,
                    "factor_id": self.factor_id,
                    "semantic_version": self.semantic_version,
                    "definition_hash": self.definition_hash,
                    "code_sha": self.code_sha,
                    "dataset_version_ids": datasets,
                    "feature_version_ids": features,
                    "model_version_ids": models,
                    "created_by": self.created_by,
                    "created_at": _canonical_time(created_at),
                }
            ),
        )

    def transition(
        self,
        event: FactorLifecycleEvent,
        *,
        validation_report: ValidationReport | None = None,
        approval: PromotionApproval | None = None,
        scope: ApprovalScope | str | None = None,
    ) -> FactorVersion:
        if not isinstance(event, FactorLifecycleEvent):
            raise TypeError("event must be a FactorLifecycleEvent")
        if event.from_status is not self.status:
            raise ValueError("lifecycle event from_status does not match current status")
        if self.lifecycle_events and event.occurred_at < self.lifecycle_events[-1].occurred_at:
            raise ValueError("lifecycle events must be time ordered")
        if event.occurred_at < self.created_at:
            raise ValueError("lifecycle event cannot precede factor creation")

        bindings = self.promotion_bindings
        if event.to_status is FactorLifecycleStatus.PRODUCTION:
            if not isinstance(validation_report, ValidationReport):
                raise FactorPromotionError("production requires a ValidationReport")
            if not isinstance(approval, PromotionApproval):
                raise FactorPromotionError("production requires an Approval")
            if scope is None:
                raise FactorPromotionError("production requires an Approval scope")
            requested_scope = ApprovalScope(scope)
            if validation_report.factor_version_id != self.factor_version_id:
                raise FactorPromotionError("validation report targets another FactorVersion")
            if not validation_report.passes_promotion_gate:
                raise FactorPromotionError("validation report did not pass the promotion gate")
            if not approval.authorizes(
                factor_version_id=self.factor_version_id,
                validation_report=validation_report,
                scope=requested_scope,
            ):
                raise FactorPromotionError(
                    "Approval does not authorize this factor, report, and scope"
                )
            if validation_report.created_at > approval.decided_at:
                raise FactorPromotionError("Approval cannot precede its ValidationReport")
            if approval.decided_at > event.occurred_at:
                raise FactorPromotionError("production event cannot precede Approval")
            if approval.approval_id in {item.approval_id for item in bindings}:
                raise FactorPromotionError("reactivation requires a new Approval")
            bindings = (
                *bindings,
                PromotionBinding(
                    validation_report_id=validation_report.report_id,
                    validation_report_hash=validation_report.content_hash,
                    approval_id=approval.approval_id,
                    approval_hash=approval.content_hash,
                    scope=requested_scope,
                    bound_at=event.occurred_at,
                ),
            )
        elif any(value is not None for value in (validation_report, approval, scope)):
            raise ValueError("validation and approval bindings are only valid for production")

        return replace(
            self,
            status=event.to_status,
            lifecycle_events=(*self.lifecycle_events, event),
            promotion_bindings=bindings,
        )

    def is_authorized_for(self, scope: ApprovalScope | str) -> bool:
        try:
            requested_scope = ApprovalScope(scope)
        except ValueError:
            return False
        return (
            self.status is FactorLifecycleStatus.PRODUCTION
            and bool(self.promotion_bindings)
            and self.promotion_bindings[-1].scope is requested_scope
        )
