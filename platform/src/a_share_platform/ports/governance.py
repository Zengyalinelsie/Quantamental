"""Repository port for the immutable governance ledger."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.governance import Artifact, DatasetVersion, LineageEdge, RunRecord


class GovernanceStoreUnavailable(RuntimeError):
    """The durable governance ledger cannot currently be reached."""


class ArtifactObjectUnavailable(RuntimeError):
    """A registered Artifact object cannot currently be read."""


class ArtifactIntegrityError(RuntimeError):
    """Registered Artifact metadata and immutable object bytes do not agree."""


class ArtifactObjectReader(Protocol):
    def read(self, value: Artifact) -> bytes: ...


class DatasetVersionRepository(Protocol):
    def register_dataset(self, value: DatasetVersion) -> DatasetVersion: ...

    def list_datasets(self) -> tuple[DatasetVersion, ...]: ...


class GovernanceRepository(DatasetVersionRepository, Protocol):

    def register_run(self, value: RunRecord) -> RunRecord: ...

    def get_run(self, run_id: str) -> RunRecord | None: ...

    def append_run_state(self, value: RunRecord) -> RunRecord: ...

    def list_runs(self) -> tuple[RunRecord, ...]: ...

    def register_artifact(self, value: Artifact) -> Artifact: ...

    def get_artifact(self, artifact_id: str) -> Artifact | None: ...

    def get_artifact_by_hash(self, content_hash: str) -> Artifact | None: ...

    def list_artifacts(self) -> tuple[Artifact, ...]: ...

    def register_artifact_with_lineage(
        self,
        value: Artifact,
        lineage: tuple[LineageEdge, ...],
    ) -> Artifact: ...

    def register_lineage(self, value: LineageEdge) -> LineageEdge: ...

    def list_lineage(self) -> tuple[LineageEdge, ...]: ...

    def list_lineage_for(self, downstream_id: str) -> tuple[LineageEdge, ...]: ...
