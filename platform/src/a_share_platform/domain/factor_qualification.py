"""Immutable evidence contracts for real P4 factor qualification audits."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum

from .backfill import DatasetQualityStatus
from .experiments import ExperimentRun
from .factor_lifecycle import FactorLifecycleStatus, FactorVersion, ValidationReport
from .factor_readiness import FactorDataRole, FactorStudyReadiness
from .governance import DatasetVersion
from .pit import DataTrustState

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


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _day(value: date | None, field_name: str) -> date | None:
    if value is not None and (not isinstance(value, date) or isinstance(value, datetime)):
        raise TypeError(f"{field_name} must be a date or None")
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


def _identifiers(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    selected = tuple(sorted(values))
    for value in selected:
        _text(value, field_name)
    if len(selected) != len(set(selected)):
        raise ValueError(f"{field_name} must be unique")
    return selected


class FactorRoleAvailability(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class FactorQualificationRequest:
    request_id: str
    requested_universe_id: str
    benchmark_id: str
    expected_entity_count: int
    start_date: date
    end_date: date
    minimum_coverage: Decimal
    threshold_source: str
    decision_time_policy_version: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.request_id, "request_id"),
            (self.requested_universe_id, "requested_universe_id"),
            (self.benchmark_id, "benchmark_id"),
            (self.threshold_source, "threshold_source"),
            (self.decision_time_policy_version, "decision_time_policy_version"),
        ):
            _text(value, field_name)
        if type(self.expected_entity_count) is not int or self.expected_entity_count <= 0:
            raise ValueError("expected_entity_count must be a positive integer")
        start = _day(self.start_date, "start_date")
        end = _day(self.end_date, "end_date")
        if start is None or end is None or end < start:
            raise ValueError("qualification study window must be non-empty")
        if not isinstance(self.minimum_coverage, Decimal):
            raise TypeError("minimum_coverage must be a Decimal")
        if (
            not self.minimum_coverage.is_finite()
            or not Decimal(0) <= self.minimum_coverage <= Decimal(1)
        ):
            raise ValueError("minimum_coverage must be between zero and one")
        _aware(self.evaluated_at, "evaluated_at")

    @property
    def decision_time_policy_hash(self) -> str:
        return hashlib.sha256(self.decision_time_policy_version.encode()).hexdigest()

    def hash_payload(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "requested_universe_id": self.requested_universe_id,
            "benchmark_id": self.benchmark_id,
            "expected_entity_count": self.expected_entity_count,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "minimum_coverage": str(self.minimum_coverage),
            "threshold_source": self.threshold_source,
            "decision_time_policy_version": self.decision_time_policy_version,
            "evaluated_at": _canonical_time(self.evaluated_at),
        }


@dataclass(frozen=True)
class FactorQualificationRoleEvidence:
    role: FactorDataRole
    availability: FactorRoleAvailability
    upstream_dataset_version_ids: tuple[str, ...]
    upstream_source_ids: tuple[str, ...]
    trust_state: DataTrustState
    quality_status: DatasetQualityStatus
    row_count: int
    observed_entity_count: int
    expected_entity_count: int
    start_date: date | None
    end_date: date | None
    availability_enforced: bool
    lineage_complete: bool
    query_hash: str
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        role = FactorDataRole(self.role)
        availability = FactorRoleAvailability(self.availability)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "availability", availability)
        object.__setattr__(
            self,
            "upstream_dataset_version_ids",
            _identifiers(
                self.upstream_dataset_version_ids,
                "upstream_dataset_version_ids",
            ),
        )
        object.__setattr__(
            self,
            "upstream_source_ids",
            _identifiers(self.upstream_source_ids, "upstream_source_ids"),
        )
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        object.__setattr__(
            self,
            "quality_status",
            DatasetQualityStatus(self.quality_status),
        )
        for value, field_name in (
            (self.row_count, "row_count"),
            (self.observed_entity_count, "observed_entity_count"),
            (self.expected_entity_count, "expected_entity_count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.expected_entity_count == 0:
            raise ValueError("expected_entity_count must be positive")
        start = _day(self.start_date, "start_date")
        end = _day(self.end_date, "end_date")
        if (start is None) != (end is None):
            raise ValueError("role dates must both be present or both be absent")
        if start is not None and end is not None and end < start:
            raise ValueError("role end_date cannot precede start_date")
        if type(self.availability_enforced) is not bool:
            raise TypeError("availability_enforced must be a boolean")
        if type(self.lineage_complete) is not bool:
            raise TypeError("lineage_complete must be a boolean")
        _hash(self.query_hash, "query_hash")
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)
        if availability is FactorRoleAvailability.UNAVAILABLE:
            if self.row_count != 0 or self.observed_entity_count != 0:
                raise ValueError("unavailable role evidence must have zero observations")
            if start is not None or end is not None:
                raise ValueError("unavailable role evidence cannot claim observed dates")
        elif self.row_count == 0:
            raise ValueError("observed role evidence must have rows")

    @property
    def coverage_ratio(self) -> Decimal:
        return min(
            Decimal(1),
            Decimal(self.observed_entity_count) / Decimal(self.expected_entity_count),
        )

    def hash_payload(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "availability": self.availability.value,
            "upstream_dataset_version_ids": self.upstream_dataset_version_ids,
            "upstream_source_ids": self.upstream_source_ids,
            "trust_state": self.trust_state.value,
            "quality_status": self.quality_status.value,
            "row_count": self.row_count,
            "observed_entity_count": self.observed_entity_count,
            "expected_entity_count": self.expected_entity_count,
            "coverage_ratio": str(self.coverage_ratio),
            "start_date": None if self.start_date is None else self.start_date.isoformat(),
            "end_date": None if self.end_date is None else self.end_date.isoformat(),
            "availability_enforced": self.availability_enforced,
            "lineage_complete": self.lineage_complete,
            "query_hash": self.query_hash,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class FactorQualificationTarget:
    factor_key: str
    factor_id: str
    factor_version_id: str
    feature_id: str
    feature_version: str
    definition_hash: str
    required_metric_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.factor_key, "factor_key"),
            (self.factor_id, "factor_id"),
            (self.factor_version_id, "factor_version_id"),
            (self.feature_id, "feature_id"),
            (self.feature_version, "feature_version"),
        ):
            _text(value, field_name)
        _hash(self.definition_hash, "definition_hash")
        metrics = _identifiers(self.required_metric_codes, "required_metric_codes")
        if not metrics:
            raise ValueError("required_metric_codes must not be empty")
        object.__setattr__(self, "required_metric_codes", metrics)


@dataclass(frozen=True)
class FactorQualificationSnapshot:
    request: FactorQualificationRequest
    candidate_universe_version_id: str
    candidate_universe_version_ids: tuple[str, ...]
    role_evidence: tuple[FactorQualificationRoleEvidence, ...]
    observed_pit_metric_codes: tuple[str, ...]
    feature_snapshot_counts: tuple[tuple[str, int], ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, FactorQualificationRequest):
            raise TypeError("request must be a FactorQualificationRequest")
        _text(self.candidate_universe_version_id, "candidate_universe_version_id")
        candidates = _identifiers(
            self.candidate_universe_version_ids,
            "candidate_universe_version_ids",
        )
        if self.candidate_universe_version_id not in candidates:
            raise ValueError("primary candidate UniverseVersion must be in candidates")
        object.__setattr__(self, "candidate_universe_version_ids", candidates)
        roles = tuple(self.role_evidence)
        if any(not isinstance(value, FactorQualificationRoleEvidence) for value in roles):
            raise TypeError("role_evidence must contain role evidence values")
        role_names = tuple(value.role for value in roles)
        if set(role_names) != set(FactorDataRole):
            raise ValueError("snapshot must contain every required role exactly once")
        if len(role_names) != len(set(role_names)):
            raise ValueError("snapshot required role evidence must be unique")
        roles = tuple(sorted(roles, key=lambda value: value.role.value))
        object.__setattr__(self, "role_evidence", roles)
        object.__setattr__(
            self,
            "observed_pit_metric_codes",
            _identifiers(self.observed_pit_metric_codes, "observed_pit_metric_codes"),
        )
        feature_counts = tuple(sorted(self.feature_snapshot_counts))
        names = tuple(name for name, _ in feature_counts)
        if len(names) != len(set(names)):
            raise ValueError("feature_snapshot_counts feature ids must be unique")
        for name, count in feature_counts:
            _text(name, "feature_snapshot_counts feature_id")
            if type(count) is not int or count < 0:
                raise ValueError("feature snapshot count must be non-negative")
        object.__setattr__(self, "feature_snapshot_counts", feature_counts)
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    def feature_snapshot_count(self, feature_id: str) -> int:
        return dict(self.feature_snapshot_counts).get(feature_id, 0)

    def hash_payload(self) -> dict[str, object]:
        return {
            "request": self.request.hash_payload(),
            "candidate_universe_version_id": self.candidate_universe_version_id,
            "candidate_universe_version_ids": self.candidate_universe_version_ids,
            "role_evidence": [value.hash_payload() for value in self.role_evidence],
            "observed_pit_metric_codes": self.observed_pit_metric_codes,
            "feature_snapshot_counts": self.feature_snapshot_counts,
        }


@dataclass(frozen=True)
class FactorQualificationRoleDataset:
    role: FactorDataRole
    dataset: DatasetVersion
    manifest: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", FactorDataRole(self.role))
        if not isinstance(self.dataset, DatasetVersion):
            raise TypeError("dataset must be a DatasetVersion")
        if not isinstance(self.manifest, bytes) or not self.manifest:
            raise ValueError("manifest must be non-empty bytes")
        expected = "sha256:" + hashlib.sha256(self.manifest).hexdigest()
        if self.dataset.content_hash != expected:
            raise ValueError("role dataset hash does not match manifest")


@dataclass(frozen=True)
class FactorQualificationAudit:
    audit_id: str
    target: FactorQualificationTarget
    snapshot: FactorQualificationSnapshot
    role_datasets: tuple[FactorQualificationRoleDataset, ...]
    readiness: FactorStudyReadiness
    factor_version: FactorVersion
    experiment_run: ExperimentRun
    validation_report: ValidationReport
    artifact_id: str
    artifact_hash: str
    artifact_payload: bytes
    created_at: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.audit_id, "audit_id")
        if not isinstance(self.target, FactorQualificationTarget):
            raise TypeError("target must be a FactorQualificationTarget")
        if not isinstance(self.snapshot, FactorQualificationSnapshot):
            raise TypeError("snapshot must be a FactorQualificationSnapshot")
        datasets = tuple(self.role_datasets)
        if len(datasets) != len(FactorDataRole) or {
            value.role for value in datasets
        } != set(FactorDataRole):
            raise ValueError("audit must bind every qualification role dataset")
        object.__setattr__(
            self,
            "role_datasets",
            tuple(sorted(datasets, key=lambda value: value.role.value)),
        )
        if not isinstance(self.readiness, FactorStudyReadiness):
            raise TypeError("readiness must be FactorStudyReadiness")
        if self.readiness.permitted:
            raise ValueError("insufficient-data qualification audit cannot be permitted")
        if not isinstance(self.factor_version, FactorVersion):
            raise TypeError("factor_version must be a FactorVersion")
        if self.factor_version.status not in {
            FactorLifecycleStatus.DRAFT,
            FactorLifecycleStatus.RESEARCH,
        }:
            raise ValueError("qualification factor must remain draft or research")
        if not isinstance(self.experiment_run, ExperimentRun):
            raise TypeError("experiment_run must be an ExperimentRun")
        if self.experiment_run.status.value != "failed" or self.experiment_run.metrics:
            raise ValueError("qualification ExperimentRun must fail without metrics")
        if not isinstance(self.validation_report, ValidationReport):
            raise TypeError("validation_report must be a ValidationReport")
        if self.validation_report.passes_promotion_gate:
            raise ValueError("qualification ValidationReport cannot pass promotion")
        _text(self.artifact_id, "artifact_id")
        _hash(self.artifact_hash, "artifact_hash")
        if not isinstance(self.artifact_payload, bytes) or not self.artifact_payload:
            raise ValueError("artifact_payload must be non-empty bytes")
        if hashlib.sha256(self.artifact_payload).hexdigest() != self.artifact_hash:
            raise ValueError("artifact_hash does not match artifact_payload")
        if self.artifact_hash not in {
            value.content_hash for value in self.experiment_run.artifacts
        }:
            raise ValueError("ExperimentRun does not bind qualification artifact")
        if self.artifact_hash not in self.validation_report.artifact_hashes:
            raise ValueError("ValidationReport does not bind qualification artifact")
        _aware(self.created_at, "created_at")
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(
                {
                    "audit_id": self.audit_id,
                    "target": self.target.factor_version_id,
                    "snapshot_hash": self.snapshot.content_hash,
                    "readiness_blockers": self.readiness.blockers,
                    "factor_version_hash": self.factor_version.content_hash,
                    "experiment_run_hash": self.experiment_run.content_hash,
                    "validation_report_hash": self.validation_report.content_hash,
                    "artifact_hash": self.artifact_hash,
                    "created_at": _canonical_time(self.created_at),
                }
            ),
        )


__all__ = [
    "FactorQualificationAudit",
    "FactorQualificationRequest",
    "FactorQualificationRoleDataset",
    "FactorQualificationRoleEvidence",
    "FactorQualificationSnapshot",
    "FactorQualificationTarget",
    "FactorRoleAvailability",
]
