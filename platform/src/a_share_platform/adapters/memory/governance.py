"""In-memory implementation of the governance repository port."""

from __future__ import annotations

from dataclasses import replace
from typing import TypeVar

from a_share_platform.domain.governance import (
    Artifact,
    DatasetVersion,
    InvalidRunTransitionError,
    LineageEdge,
    RunRecord,
    RunStatus,
    VersionConflictError,
)

_ImmutableValue = TypeVar("_ImmutableValue", DatasetVersion, Artifact)


class InMemoryGovernanceRepository:
    def __init__(self) -> None:
        self._datasets: dict[str, DatasetVersion] = {}
        self._dataset_hashes: dict[str, str] = {}
        self._runs: dict[str, RunRecord] = {}
        self._run_histories: dict[str, list[RunRecord]] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._artifact_hashes: dict[str, str] = {}
        self._lineage: dict[tuple[str, str, str], LineageEdge] = {}

    @staticmethod
    def _register_immutable(
        values: dict[str, _ImmutableValue],
        hashes: dict[str, str],
        *,
        identifier: str,
        content_hash: str,
        value: _ImmutableValue,
    ) -> _ImmutableValue:
        if existing := values.get(identifier):
            if existing != value:
                raise VersionConflictError(f"immutable identifier conflict: {identifier}")
            return existing
        if owner := hashes.get(content_hash):
            raise VersionConflictError(
                f"content hash {content_hash} is already bound to {owner}"
            )
        values[identifier] = value
        hashes[content_hash] = identifier
        return value

    def register_dataset(self, value: DatasetVersion) -> DatasetVersion:
        return self._register_immutable(
            self._datasets,
            self._dataset_hashes,
            identifier=value.dataset_version_id,
            content_hash=value.content_hash,
            value=value,
        )

    def list_datasets(self) -> tuple[DatasetVersion, ...]:
        return tuple(self._datasets.values())

    def register_run(self, value: RunRecord) -> RunRecord:
        if existing := self._runs.get(value.run_id):
            if existing != value:
                raise VersionConflictError(f"run identifier conflict: {value.run_id}")
            return existing
        self._runs[value.run_id] = value
        self._run_histories[value.run_id] = [value]
        return value

    def get_run(self, run_id: str) -> RunRecord | None:
        return self._runs.get(run_id)

    def append_run_state(self, value: RunRecord) -> RunRecord:
        current = self._runs.get(value.run_id)
        if current is None:
            raise KeyError(value.run_id)
        if current.status is RunStatus.PENDING and value.status is RunStatus.RUNNING:
            expected = replace(current, status=RunStatus.RUNNING)
        elif current.status is RunStatus.RUNNING and value.status.terminal:
            expected = replace(
                current,
                status=value.status,
                finished_at=value.finished_at,
                failure_reason=value.failure_reason,
            )
        else:
            raise InvalidRunTransitionError(
                f"run {value.run_id} cannot transition from "
                f"{current.status.value} to {value.status.value}"
            )
        if expected != value:
            raise VersionConflictError(
                f"run transition changes immutable fields: {value.run_id}"
            )
        self._runs[value.run_id] = value
        self._run_histories[value.run_id].append(value)
        return value

    def list_runs(self) -> tuple[RunRecord, ...]:
        return tuple(self._runs.values())

    def run_history(self, run_id: str) -> tuple[RunRecord, ...]:
        return tuple(self._run_histories.get(run_id, ()))

    def register_artifact(self, value: Artifact) -> Artifact:
        if value.run_id not in self._runs:
            raise ValueError(f"artifact run does not exist: {value.run_id}")
        return self._register_immutable(
            self._artifacts,
            self._artifact_hashes,
            identifier=value.artifact_id,
            content_hash=value.content_hash,
            value=value,
        )

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        return self._artifacts.get(artifact_id)

    def get_artifact_by_hash(self, content_hash: str) -> Artifact | None:
        artifact_id = self._artifact_hashes.get(content_hash)
        return None if artifact_id is None else self._artifacts[artifact_id]

    def list_artifacts(self) -> tuple[Artifact, ...]:
        return tuple(self._artifacts.values())

    def register_artifact_with_lineage(
        self,
        value: Artifact,
        lineage: tuple[LineageEdge, ...],
    ) -> Artifact:
        edges = tuple(lineage)
        if any(not isinstance(edge, LineageEdge) for edge in edges):
            raise TypeError("lineage must contain LineageEdge values")
        stored = self.register_artifact(value)
        for edge in edges:
            self.register_lineage(edge)
        return stored

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        key = (value.upstream_id, value.downstream_id, value.relation)
        if existing := self._lineage.get(key):
            return existing
        self._lineage[key] = value
        return value

    def list_lineage(self) -> tuple[LineageEdge, ...]:
        return tuple(self._lineage.values())

    def list_lineage_for(self, downstream_id: str) -> tuple[LineageEdge, ...]:
        return tuple(
            edge for edge in self._lineage.values() if edge.downstream_id == downstream_id
        )
