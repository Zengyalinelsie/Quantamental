"""Use cases for registering immutable governance objects and run outcomes."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from a_share_platform.domain.governance import (
    Artifact,
    DatasetVersion,
    InvalidRunTransitionError,
    LineageEdge,
    RunRecord,
    RunStatus,
)
from a_share_platform.ports.governance import GovernanceRepository


class GovernanceLedger:
    def __init__(self, repository: GovernanceRepository) -> None:
        self._repository = repository

    def register_dataset(self, value: DatasetVersion) -> DatasetVersion:
        return self._repository.register_dataset(value)

    def register_run(self, value: RunRecord) -> RunRecord:
        return self._repository.register_run(value)

    def finish_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        finished_at: datetime,
        failure_reason: str | None = None,
    ) -> RunRecord:
        current = self._repository.get_run(run_id)
        if current is None:
            raise KeyError(run_id)
        status = RunStatus(status)
        if current.status is not RunStatus.RUNNING or not status.terminal:
            raise InvalidRunTransitionError(
                f"run {run_id} cannot transition from {current.status.value} to {status.value}"
            )
        updated = replace(
            current,
            status=status,
            finished_at=finished_at,
            failure_reason=failure_reason,
        )
        return self._repository.append_run_state(updated)

    def register_artifact(self, value: Artifact) -> Artifact:
        if self._repository.get_run(value.run_id) is None:
            raise ValueError(f"artifact run does not exist: {value.run_id}")
        return self._repository.register_artifact(value)

    def register_lineage(self, value: LineageEdge) -> LineageEdge:
        return self._repository.register_lineage(value)
