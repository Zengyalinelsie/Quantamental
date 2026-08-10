"""In-memory implementation of the governance repository port."""

from __future__ import annotations

from typing import TypeVar

from a_share_platform.domain.governance import (
    Artifact,
    DatasetVersion,
    LineageEdge,
    RunRecord,
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
        if value.run_id not in self._runs:
            raise KeyError(value.run_id)
        self._runs[value.run_id] = value
        self._run_histories[value.run_id].append(value)
        return value

    def list_runs(self) -> tuple[RunRecord, ...]:
        return tuple(self._runs.values())

    def run_history(self, run_id: str) -> tuple[RunRecord, ...]:
        return tuple(self._run_histories.get(run_id, ()))

    def register_artifact(self, value: Artifact) -> Artifact:
        return self._register_immutable(
            self._artifacts,
            self._artifact_hashes,
            identifier=value.artifact_id,
            content_hash=value.content_hash,
            value=value,
        )

    def list_artifacts(self) -> tuple[Artifact, ...]:
        return tuple(self._artifacts.values())

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        key = (value.upstream_id, value.downstream_id, value.relation)
        if existing := self._lineage.get(key):
            return existing
        self._lineage[key] = value
        return value

    def list_lineage(self) -> tuple[LineageEdge, ...]:
        return tuple(self._lineage.values())
