"""Repository port for immutable reproducible experiment runs."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.experiments import ExperimentRun


class ExperimentStoreUnavailable(RuntimeError):
    """The durable experiment ledger cannot currently be reached or configured."""


class ExperimentRunRepository(Protocol):
    def save_run(self, value: ExperimentRun) -> ExperimentRun: ...

    def get_run(self, run_id: str) -> ExperimentRun | None: ...

    def list_runs(self) -> tuple[ExperimentRun, ...]: ...


__all__ = ["ExperimentRunRepository", "ExperimentStoreUnavailable"]
