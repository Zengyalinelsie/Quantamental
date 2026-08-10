"""Immutable governance objects for data, runs, artifacts, and lineage."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .run_context import RunContext

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _require_content_hash(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")
    return value


class VersionConflictError(RuntimeError):
    """An immutable identifier or content hash was reused inconsistently."""


class InvalidRunTransitionError(RuntimeError):
    """A run state transition is not permitted."""


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True)
class DatasetVersion:
    dataset_version_id: str
    content_hash: str
    created_at: datetime
    schema_version: str

    def __post_init__(self) -> None:
        _require_text(self.dataset_version_id, "dataset_version_id")
        _require_content_hash(self.content_hash)
        _require_aware(self.created_at, "created_at")
        _require_text(self.schema_version, "schema_version")


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    run_kind: str
    status: RunStatus
    context: RunContext
    created_at: datetime
    code_version: str
    environment_fingerprint: str
    finished_at: datetime | None = None
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.run_kind, "run_kind")
        status = RunStatus(self.status)
        object.__setattr__(self, "status", status)
        if not isinstance(self.context, RunContext):
            raise TypeError("context must be a RunContext")
        created_at = _require_aware(self.created_at, "created_at")
        _require_text(self.code_version, "code_version")
        _require_text(self.environment_fingerprint, "environment_fingerprint")
        if status.terminal:
            if self.finished_at is None:
                raise ValueError("terminal run requires finished_at")
            finished_at = _require_aware(self.finished_at, "finished_at")
            if finished_at < created_at:
                raise ValueError("finished_at cannot precede created_at")
        elif self.finished_at is not None:
            raise ValueError("non-terminal run must not have finished_at")
        if status is RunStatus.FAILED:
            _require_text(self.failure_reason or "", "failure_reason")
        elif self.failure_reason is not None:
            raise ValueError("failure_reason is only valid for failed runs")


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    run_id: str
    content_hash: str
    media_type: str
    storage_uri: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.run_id, "run_id")
        _require_content_hash(self.content_hash)
        _require_text(self.media_type, "media_type")
        _require_text(self.storage_uri, "storage_uri")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True)
class LineageEdge:
    upstream_id: str
    downstream_id: str
    relation: str

    def __post_init__(self) -> None:
        _require_text(self.upstream_id, "upstream_id")
        _require_text(self.downstream_id, "downstream_id")
        _require_text(self.relation, "relation")
        if self.upstream_id == self.downstream_id:
            raise ValueError("lineage upstream_id and downstream_id must differ")
