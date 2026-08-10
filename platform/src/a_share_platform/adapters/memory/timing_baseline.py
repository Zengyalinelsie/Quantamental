"""In-memory persistence for the P3 passive timing baseline."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date

from a_share_platform.domain.governance import (
    DatasetVersion,
    LineageEdge,
    RunRecord,
    VersionConflictError,
)
from a_share_platform.domain.timing import BenchmarkCloseBatch


class InMemoryTimingBaselineStore:
    """Small immutable store used by the use-case tests."""

    def __init__(
        self,
        *,
        known_universe_versions: set[tuple[str, str]] | None = None,
    ) -> None:
        self.known_universe_versions = set(known_universe_versions or ())
        self.datasets: list[DatasetVersion] = []
        self.dataset_metadata: dict[str, dict[str, object]] = {}
        self.batches: list[tuple[str, BenchmarkCloseBatch]] = []
        self.runs: list[RunRecord] = []
        self.lineage: list[LineageEdge] = []

    def has_universe_version(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> bool:
        if not isinstance(effective_session, date):
            raise TypeError("effective_session must be a date")
        return (benchmark_id, universe_version_id) in self.known_universe_versions

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: Mapping[str, object],
    ) -> DatasetVersion:
        normalized = json.loads(json.dumps(metadata, sort_keys=True))
        assert isinstance(normalized, dict)
        for existing in self.datasets:
            if existing.dataset_version_id == value.dataset_version_id:
                if existing != value or self.dataset_metadata[value.dataset_version_id] != normalized:
                    raise VersionConflictError(
                        f"immutable timing dataset conflict: {value.dataset_version_id}"
                    )
                return existing
            if existing.content_hash == value.content_hash:
                raise VersionConflictError(
                    f"timing dataset content hash already belongs to {existing.dataset_version_id}"
                )
        self.datasets.append(value)
        self.dataset_metadata[value.dataset_version_id] = normalized
        return value

    def save_benchmark_batch(
        self,
        dataset_version_id: str,
        batch: BenchmarkCloseBatch,
    ) -> None:
        if not any(
            item.dataset_version_id == dataset_version_id for item in self.datasets
        ):
            raise KeyError(dataset_version_id)
        for existing_id, existing in self.batches:
            if existing_id == dataset_version_id:
                if existing != batch:
                    raise VersionConflictError(
                        f"immutable timing benchmark batch conflict: {dataset_version_id}"
                    )
                return
        self.batches.append((dataset_version_id, batch))

    def register_run(self, value: RunRecord) -> RunRecord:
        for existing in self.runs:
            if existing.run_id == value.run_id:
                if existing != value:
                    raise VersionConflictError(f"run identifier conflict: {value.run_id}")
                return existing
        self.runs.append(value)
        return value

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        for existing in self.lineage:
            if existing == value:
                return existing
        self.lineage.append(value)
        return value
