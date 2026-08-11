"""Explicit in-memory test adapter and unavailable runtime adapter for experiments."""

from __future__ import annotations

from typing import Never

from a_share_platform.domain.experiments import (
    ExperimentRun,
    ExperimentRunConflict,
)
from a_share_platform.ports.experiments import ExperimentStoreUnavailable


class InMemoryExperimentRunRepository:
    """Append-only adapter intended for contract tests, never runtime demo data."""

    def __init__(self) -> None:
        self._runs: dict[str, ExperimentRun] = {}

    def save_run(self, value: ExperimentRun) -> ExperimentRun:
        if not isinstance(value, ExperimentRun):
            raise TypeError("value must be an ExperimentRun")
        existing = self._runs.get(value.run_id)
        if existing is not None:
            if existing != value:
                raise ExperimentRunConflict(
                    f"immutable experiment run conflict: {value.run_id}"
                )
            return existing
        self._runs[value.run_id] = value
        return value

    def get_run(self, run_id: str) -> ExperimentRun | None:
        return self._runs.get(run_id)

    def list_runs(self) -> tuple[ExperimentRun, ...]:
        return tuple(self._runs[key] for key in sorted(self._runs))


class UnavailableExperimentRunRepository:
    """Fail closed when durable experiment persistence is not configured."""

    def __init__(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("unavailable experiment store reason must not be empty")
        self._reason = reason

    def _raise(self) -> Never:
        raise ExperimentStoreUnavailable(self._reason)

    def save_run(self, value: ExperimentRun) -> ExperimentRun:
        del value
        self._raise()

    def get_run(self, run_id: str) -> ExperimentRun | None:
        del run_id
        self._raise()

    def list_runs(self) -> tuple[ExperimentRun, ...]:
        self._raise()


__all__ = [
    "InMemoryExperimentRunRepository",
    "UnavailableExperimentRunRepository",
]
