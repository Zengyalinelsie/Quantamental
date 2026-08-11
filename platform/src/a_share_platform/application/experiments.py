"""Application service for registering and reading reproducible experiments."""

from __future__ import annotations

from a_share_platform.domain.experiments import ExperimentRun
from a_share_platform.ports.experiments import ExperimentRunRepository


class ExperimentRunService:
    def __init__(self, repository: ExperimentRunRepository) -> None:
        self._repository = repository

    def create_run(self, value: ExperimentRun) -> ExperimentRun:
        return self._repository.save_run(value)

    def get_run(self, run_id: str) -> ExperimentRun | None:
        if not isinstance(run_id, str):
            raise TypeError("run_id must be a string")
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        return self._repository.get_run(run_id)

    def list_runs(self) -> tuple[ExperimentRun, ...]:
        return self._repository.list_runs()


__all__ = ["ExperimentRunService"]
