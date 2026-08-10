"""Fail-closed data qualification for P4 historical factor studies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .backfill import DatasetQualityStatus
from .pit import DataTrustState
from .run_context import DataMode, DeploymentStage, RunContext


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _plain_date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _coverage(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
        raise ValueError(f"{field_name} must be between 0 and 1")
    return value


class FactorDataRole(str, Enum):
    """Data domains required before a P4 historical result can be evaluated."""

    FINANCIAL_FACT = "financial_fact"
    HISTORICAL_UNIVERSE = "historical_universe"
    INDUSTRY_CLASSIFICATION = "industry_classification"
    RAW_DAILY_BAR = "raw_daily_bar"
    SHARE_CAPITAL = "share_capital"
    CORPORATE_ACTION = "corporate_action"
    BENCHMARK_BAR = "benchmark_bar"
    FORWARD_RETURN_LABEL = "forward_return_label"


class FactorDataAvailabilityPolicy(str, Enum):
    """Feature inputs and future labels have deliberately different clocks."""

    DECISION_TIME_CUTOFF = "decision_time_cutoff"
    LABEL_OUTCOME_ONLY = "label_outcome_only"


_EXPECTED_POLICY = {
    role: (
        FactorDataAvailabilityPolicy.LABEL_OUTCOME_ONLY
        if role is FactorDataRole.FORWARD_RETURN_LABEL
        else FactorDataAvailabilityPolicy.DECISION_TIME_CUTOFF
    )
    for role in FactorDataRole
}


@dataclass(frozen=True)
class FactorDataRequirement:
    """A versioned coverage threshold selected by the research specification."""

    role: FactorDataRole
    minimum_coverage: Decimal
    threshold_source: str
    availability_policy: FactorDataAvailabilityPolicy

    def __post_init__(self) -> None:
        role = FactorDataRole(self.role)
        policy = FactorDataAvailabilityPolicy(self.availability_policy)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "availability_policy", policy)
        _coverage(self.minimum_coverage, "minimum_coverage")
        _text(self.threshold_source, "threshold_source")
        if policy is not _EXPECTED_POLICY[role]:
            raise ValueError(
                f"{role.value} requires availability_policy="
                f"{_EXPECTED_POLICY[role].value}"
            )


@dataclass(frozen=True)
class FactorDataBinding:
    """One immutable dataset qualification record bound to a study."""

    role: FactorDataRole
    dataset_version_id: str
    trust_state: DataTrustState
    quality_status: DatasetQualityStatus
    coverage_ratio: Decimal
    start_date: date
    end_date: date
    availability_policy: FactorDataAvailabilityPolicy
    availability_enforced: bool
    lineage_complete: bool
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", FactorDataRole(self.role))
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        object.__setattr__(
            self,
            "quality_status",
            DatasetQualityStatus(self.quality_status),
        )
        object.__setattr__(
            self,
            "availability_policy",
            FactorDataAvailabilityPolicy(self.availability_policy),
        )
        _text(self.dataset_version_id, "dataset_version_id")
        _coverage(self.coverage_ratio, "coverage_ratio")
        start = _plain_date(self.start_date, "start_date")
        end = _plain_date(self.end_date, "end_date")
        if end < start:
            raise ValueError("end_date cannot precede start_date")
        if type(self.availability_enforced) is not bool:
            raise TypeError("availability_enforced must be a boolean")
        if type(self.lineage_complete) is not bool:
            raise TypeError("lineage_complete must be a boolean")
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True)
class FactorStudySpec:
    """Frozen data contract for a historical factor study, not its outcome."""

    study_id: str
    run_context: RunContext
    universe_version_id: str
    benchmark_id: str
    start_date: date
    end_date: date
    decision_time_policy_version: str
    requirements: tuple[FactorDataRequirement, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.study_id, "study_id"),
            (self.universe_version_id, "universe_version_id"),
            (self.benchmark_id, "benchmark_id"),
            (self.decision_time_policy_version, "decision_time_policy_version"),
        ):
            _text(value, field_name)
        if not isinstance(self.run_context, RunContext):
            raise TypeError("run_context must be a RunContext")
        start = _plain_date(self.start_date, "start_date")
        end = _plain_date(self.end_date, "end_date")
        if end < start:
            raise ValueError("end_date cannot precede start_date")
        _aware(self.created_at, "created_at")
        requirements = tuple(self.requirements)
        if not requirements or not all(
            isinstance(item, FactorDataRequirement) for item in requirements
        ):
            raise ValueError("requirements must contain FactorDataRequirement values")
        roles = tuple(item.role for item in requirements)
        if len(roles) != len(set(roles)):
            raise ValueError("factor data requirement roles must be unique")
        missing = set(FactorDataRole).difference(roles)
        if missing:
            names = ",".join(sorted(role.value for role in missing))
            raise ValueError(f"factor study is missing required data roles: {names}")
        object.__setattr__(
            self,
            "requirements",
            tuple(sorted(requirements, key=lambda item: item.role.value)),
        )


@dataclass(frozen=True)
class FactorStudyReadiness:
    study_id: str
    evaluated_at: datetime
    permitted: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    bound_dataset_version_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.study_id, "study_id")
        _aware(self.evaluated_at, "evaluated_at")
        if type(self.permitted) is not bool:
            raise TypeError("permitted must be a boolean")
        blockers = tuple(self.blockers)
        warnings = tuple(self.warnings)
        for message in (*blockers, *warnings):
            _text(message, "readiness message")
        if self.permitted == bool(blockers):
            raise ValueError("permitted readiness and blockers are inconsistent")
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "warnings", warnings)
        dataset_ids = tuple(self.bound_dataset_version_ids)
        if len(dataset_ids) != len(set(dataset_ids)):
            raise ValueError("bound dataset version identifiers must be unique")
        for dataset_id in dataset_ids:
            _text(dataset_id, "bound_dataset_version_id")
        object.__setattr__(self, "bound_dataset_version_ids", tuple(sorted(dataset_ids)))


class FactorStudyPreflight:
    """Evaluate P4 Gate input eligibility without data access or side effects."""

    def evaluate(
        self,
        spec: FactorStudySpec,
        bindings: tuple[FactorDataBinding, ...],
    ) -> FactorStudyReadiness:
        if not isinstance(spec, FactorStudySpec):
            raise TypeError("spec must be a FactorStudySpec")
        selected = tuple(bindings)
        if any(not isinstance(item, FactorDataBinding) for item in selected):
            raise TypeError("bindings must contain FactorDataBinding values")
        roles = tuple(item.role for item in selected)
        if len(roles) != len(set(roles)):
            raise ValueError("factor data binding roles must be unique")
        by_role = {item.role: item for item in selected}

        blockers: set[str] = set()
        warnings: set[str] = set()
        if spec.run_context.data_mode is not DataMode.STRICT_HISTORICAL:
            blockers.add("P4 historical factor evidence requires strict_historical data_mode")
        if spec.run_context.deployment_stage is not DeploymentStage.RESEARCH:
            blockers.add("P4 historical factor studies must use research deployment_stage")

        for requirement in spec.requirements:
            binding = by_role.get(requirement.role)
            if binding is None:
                blockers.add(f"missing required dataset role={requirement.role.value}")
                continue
            prefix = requirement.role.value
            if binding.trust_state is not DataTrustState.PIT_VERIFIED:
                blockers.add(f"{prefix} must be pit_verified")
            if binding.quality_status is DatasetQualityStatus.FAILED:
                blockers.add(f"{prefix} quality status is failed")
            elif binding.quality_status is DatasetQualityStatus.WARNED:
                warnings.add(f"{prefix} quality status is warned")
            if binding.coverage_ratio < requirement.minimum_coverage:
                blockers.add(
                    f"{prefix} coverage {binding.coverage_ratio} is below "
                    f"{requirement.minimum_coverage} from {requirement.threshold_source}"
                )
            if binding.start_date > spec.start_date or binding.end_date < spec.end_date:
                blockers.add(f"{prefix} does not cover the frozen study window")
            if binding.availability_policy is not requirement.availability_policy:
                blockers.add(
                    f"{prefix} availability policy must be "
                    f"{requirement.availability_policy.value}"
                )
            if not binding.availability_enforced:
                blockers.add(f"{prefix} availability rule is not enforced")
            if not binding.lineage_complete:
                blockers.add(f"{prefix} lineage is incomplete")
            warnings.update(f"{prefix}: {warning}" for warning in binding.warnings)

        return FactorStudyReadiness(
            study_id=spec.study_id,
            evaluated_at=spec.created_at,
            permitted=not blockers,
            blockers=tuple(sorted(blockers)),
            warnings=tuple(sorted(warnings)),
            bound_dataset_version_ids=tuple(
                sorted({binding.dataset_version_id for binding in selected})
            ),
        )
