"""Auditable bootstrap and aggregate finalization for P3.5 financial jobs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol

from a_share_platform.application.financial_backfill import FinancialBackfillPreview
from a_share_platform.domain.backfill import BackfillJobStatus, BackfillQualification
from a_share_platform.domain.financial_backfill import FinancialBackfillPlan
from a_share_platform.domain.governance import DatasetVersion, VersionConflictError
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_AGGREGATE_SCHEMA = "normalized-current-financial-aggregate:v1"


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class FinancialBackfillFinalizationError(RuntimeError):
    """Raised after a finalization failure has been durably audited."""


@dataclass(frozen=True)
class FinancialBackfillJobRecord:
    job_id: str
    plan: FinancialBackfillPlan
    qualification: BackfillQualification
    status: BackfillJobStatus
    created_at: datetime
    updated_at: datetime
    dataset_version_id: str | None = None
    failure_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.plan, FinancialBackfillPlan):
            raise TypeError("plan must be a FinancialBackfillPlan")
        if not isinstance(self.qualification, BackfillQualification):
            raise TypeError("qualification must be a BackfillQualification")
        expected_job_id = f"job:{self.plan.plan_id}"
        if self.job_id != expected_job_id:
            raise ValueError("financial job_id must be derived from plan_id")
        if self.qualification.provider_id != self.plan.provider_id:
            raise ValueError("qualification provider does not match financial plan")
        status = BackfillJobStatus(self.status)
        object.__setattr__(self, "status", status)
        created_at = _aware(self.created_at, "created_at")
        updated_at = _aware(self.updated_at, "updated_at")
        if updated_at < created_at:
            raise ValueError("updated_at cannot precede created_at")
        failures = tuple(self.failure_reasons)
        for failure in failures:
            _text(failure, "failure_reason")
        object.__setattr__(self, "failure_reasons", failures)
        if status is BackfillJobStatus.BLOCKED:
            if self.qualification.permitted or not failures:
                raise ValueError("blocked financial job requires qualification blockers")
        elif not self.qualification.permitted:
            raise ValueError("unqualified financial job must remain blocked")
        if status is BackfillJobStatus.SUCCEEDED:
            _text(self.dataset_version_id or "", "dataset_version_id")
            if failures:
                raise ValueError("succeeded financial job cannot retain failure reasons")
        elif self.dataset_version_id is not None:
            raise ValueError("only a succeeded financial job can reference a dataset")
        if status is BackfillJobStatus.FAILED and not failures:
            raise ValueError("failed financial job requires failure reasons")
        if status not in {BackfillJobStatus.BLOCKED, BackfillJobStatus.FAILED} and failures:
            raise ValueError("failure reasons are only valid for blocked or failed jobs")

    @classmethod
    def initial(cls, preview: FinancialBackfillPreview) -> FinancialBackfillJobRecord:
        failures = () if preview.qualification.permitted else preview.qualification.blockers
        status = (
            BackfillJobStatus.PLANNED
            if preview.qualification.permitted
            else BackfillJobStatus.BLOCKED
        )
        return cls(
            job_id=f"job:{preview.plan.plan_id}",
            plan=preview.plan,
            qualification=preview.qualification,
            status=status,
            created_at=preview.plan.created_at,
            updated_at=preview.plan.created_at,
            failure_reasons=failures,
        )

    def transition(
        self,
        status: BackfillJobStatus,
        *,
        at: datetime,
        dataset_version_id: str | None = None,
        failure_reasons: tuple[str, ...] = (),
    ) -> FinancialBackfillJobRecord:
        target = BackfillJobStatus(status)
        allowed = {
            BackfillJobStatus.PLANNED: {
                BackfillJobStatus.RUNNING,
                BackfillJobStatus.FAILED,
            },
            BackfillJobStatus.RUNNING: {
                BackfillJobStatus.SUCCEEDED,
                BackfillJobStatus.FAILED,
            },
            BackfillJobStatus.FAILED: {BackfillJobStatus.RUNNING},
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(
                f"invalid financial job transition {self.status.value}->{target.value}"
            )
        transitioned_at = _aware(at, "transition time")
        if transitioned_at < self.updated_at:
            raise ValueError("financial job transition cannot move backwards")
        return replace(
            self,
            status=target,
            updated_at=transitioned_at,
            dataset_version_id=dataset_version_id,
            failure_reasons=failure_reasons,
        )


@dataclass(frozen=True)
class FinancialCompletedWorkUnit:
    checkpoint_key: str
    dataset_version_id: str
    content_hash: str
    observation_count: int
    completed_at: datetime

    def __post_init__(self) -> None:
        _text(self.checkpoint_key, "checkpoint_key")
        _text(self.dataset_version_id, "dataset_version_id")
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("unit content_hash must use sha256:<64 lowercase hex chars>")
        if type(self.observation_count) is not int or self.observation_count <= 0:
            raise ValueError("observation_count must be a positive integer")
        _aware(self.completed_at, "completed_at")


class FinancialBackfillJobRepository(Protocol):
    def get_job(self, job_id: str) -> FinancialBackfillJobRecord | None: ...

    def create_job(
        self,
        value: FinancialBackfillJobRecord,
    ) -> FinancialBackfillJobRecord: ...

    def append_job_state(
        self,
        value: FinancialBackfillJobRecord,
        *,
        expected_previous_status: BackfillJobStatus,
    ) -> FinancialBackfillJobRecord: ...

    def list_completed_units(
        self,
        job_id: str,
    ) -> tuple[FinancialCompletedWorkUnit, ...]: ...

    def register_aggregate_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: Mapping[str, object],
    ) -> DatasetVersion: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class FinancialBackfillJobCoordinator:
    """Own job state around independently executed financial work units."""

    def __init__(
        self,
        *,
        repository: FinancialBackfillJobRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._clock = clock

    def bootstrap(self, preview: FinancialBackfillPreview) -> FinancialBackfillJobRecord:
        expected = FinancialBackfillJobRecord.initial(preview)
        existing = self._repository.get_job(expected.job_id)
        if existing is None:
            try:
                existing = self._repository.create_job(expected)
            except Exception:
                self._repository.rollback()
                raise
        self._require_same_preview(existing, preview)
        if existing.status in {
            BackfillJobStatus.BLOCKED,
            BackfillJobStatus.RUNNING,
            BackfillJobStatus.SUCCEEDED,
        }:
            if existing == expected:
                self._repository.commit()
            return existing
        if existing.status not in {
            BackfillJobStatus.PLANNED,
            BackfillJobStatus.FAILED,
        }:
            raise VersionConflictError("unsupported financial job bootstrap state")
        try:
            running = existing.transition(
                BackfillJobStatus.RUNNING,
                at=self._now(),
            )
            running = self._repository.append_job_state(
                running,
                expected_previous_status=existing.status,
            )
            self._repository.commit()
            return running
        except Exception:
            self._repository.rollback()
            raise

    def finalize(self, preview: FinancialBackfillPreview) -> FinancialBackfillJobRecord:
        job_id = f"job:{preview.plan.plan_id}"
        existing = self._repository.get_job(job_id)
        if existing is None:
            raise LookupError(f"financial backfill job does not exist: {job_id}")
        self._require_same_preview(existing, preview)
        if existing.status is BackfillJobStatus.SUCCEEDED:
            return existing
        if existing.status is not BackfillJobStatus.RUNNING:
            raise FinancialBackfillFinalizationError(
                "financial job must be running before finalization"
            )
        try:
            completed = self._repository.list_completed_units(job_id)
            self._require_complete(preview, completed)
            dataset, metadata = self._aggregate_dataset(existing, completed)
            dataset = self._repository.register_aggregate_dataset(
                dataset,
                metadata=metadata,
            )
            succeeded = existing.transition(
                BackfillJobStatus.SUCCEEDED,
                at=max(self._now(), dataset.created_at),
                dataset_version_id=dataset.dataset_version_id,
            )
            succeeded = self._repository.append_job_state(
                succeeded,
                expected_previous_status=BackfillJobStatus.RUNNING,
            )
            self._repository.commit()
            return succeeded
        except Exception as error:
            self._repository.rollback()
            self._audit_failure(existing, error)
            if isinstance(error, FinancialBackfillFinalizationError):
                raise
            raise FinancialBackfillFinalizationError(f"{type(error).__name__}: {error}") from error

    def fail(
        self,
        preview: FinancialBackfillPreview,
        reason: str,
    ) -> FinancialBackfillJobRecord:
        text = _text(reason, "failure reason")
        job_id = f"job:{preview.plan.plan_id}"
        existing = self._repository.get_job(job_id)
        if existing is None:
            raise LookupError(f"financial backfill job does not exist: {job_id}")
        self._require_same_preview(existing, preview)
        if existing.status is BackfillJobStatus.FAILED:
            return existing
        if existing.status not in {
            BackfillJobStatus.PLANNED,
            BackfillJobStatus.RUNNING,
        }:
            raise ValueError("terminal financial job cannot be marked failed")
        return self._audit_failure(existing, RuntimeError(text))

    def _audit_failure(
        self,
        existing: FinancialBackfillJobRecord,
        error: Exception,
    ) -> FinancialBackfillJobRecord:
        reason = f"{type(error).__name__}: {error}"
        try:
            failed = existing.transition(
                BackfillJobStatus.FAILED,
                at=self._now(),
                failure_reasons=(reason,),
            )
            failed = self._repository.append_job_state(
                failed,
                expected_previous_status=existing.status,
            )
            self._repository.commit()
            return failed
        except Exception:
            self._repository.rollback()
            raise

    @staticmethod
    def _require_same_preview(
        value: FinancialBackfillJobRecord,
        preview: FinancialBackfillPreview,
    ) -> None:
        if value.plan != preview.plan or value.qualification != preview.qualification:
            raise VersionConflictError(f"immutable financial job input conflict: {value.job_id}")

    @staticmethod
    def _require_complete(
        preview: FinancialBackfillPreview,
        completed: tuple[FinancialCompletedWorkUnit, ...],
    ) -> None:
        expected = tuple(unit.checkpoint_key for unit in preview.work_units)
        observed = tuple(item.checkpoint_key for item in completed)
        if len(observed) != len(set(observed)):
            raise FinancialBackfillFinalizationError("completed checkpoint set contains duplicates")
        if tuple(sorted(observed)) != tuple(sorted(expected)):
            missing = sorted(set(expected) - set(observed))
            extra = sorted(set(observed) - set(expected))
            raise FinancialBackfillFinalizationError(
                "completed checkpoint set does not match immutable plan; "
                f"missing={missing}; extra={extra}"
            )
        dataset_ids = tuple(item.dataset_version_id for item in completed)
        if len(dataset_ids) != len(set(dataset_ids)):
            raise FinancialBackfillFinalizationError("unit dataset identifiers must be unique")
        if any(item.completed_at < preview.plan.created_at for item in completed):
            raise FinancialBackfillFinalizationError(
                "unit completion cannot precede financial plan creation"
            )

    @staticmethod
    def _aggregate_dataset(
        job: FinancialBackfillJobRecord,
        completed: tuple[FinancialCompletedWorkUnit, ...],
    ) -> tuple[DatasetVersion, dict[str, object]]:
        if job.plan.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("financial aggregate must remain normalized_current")
        if job.plan.data_mode is not DataMode.CURRENT_RESEARCH:
            raise ValueError("financial aggregate must remain current_research")
        ordered = tuple(sorted(completed, key=lambda item: item.checkpoint_key))
        manifest: dict[str, object] = {
            "adjustment_mode": "not_applicable",
            "data_mode": DataMode.CURRENT_RESEARCH.value,
            "job_id": job.job_id,
            "kind": "financial_backfill_aggregate",
            "mapping_version_id": job.plan.mapping_version_id,
            "observation_count": sum(item.observation_count for item in ordered),
            "pit_verified": False,
            "plan_id": job.plan.plan_id,
            "provider_id": job.plan.provider_id,
            "provider_profile_version": job.plan.provider_profile_version,
            "schema_version": _AGGREGATE_SCHEMA,
            "trust_state": DataTrustState.NORMALIZED_CURRENT.value,
            "units": [
                {
                    "checkpoint_key": item.checkpoint_key,
                    "completed_at": item.completed_at.isoformat(),
                    "content_hash": item.content_hash,
                    "dataset_version_id": item.dataset_version_id,
                    "observation_count": item.observation_count,
                }
                for item in ordered
            ],
            "universe_version_id": job.plan.universe_version_id,
        }
        encoded = json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        plan_digest = hashlib.sha256(job.plan.plan_id.encode("utf-8")).hexdigest()[:24]
        dataset = DatasetVersion(
            dataset_version_id=(f"dataset:financial-backfill:{plan_digest}:aggregate:v1"),
            content_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
            created_at=max(item.completed_at for item in ordered),
            schema_version=_AGGREGATE_SCHEMA,
        )
        return dataset, {"manifest": manifest}

    def _now(self) -> datetime:
        return _aware(self._clock(), "clock")


__all__ = [
    "FinancialBackfillFinalizationError",
    "FinancialBackfillJobCoordinator",
    "FinancialBackfillJobRecord",
    "FinancialBackfillJobRepository",
    "FinancialCompletedWorkUnit",
]
