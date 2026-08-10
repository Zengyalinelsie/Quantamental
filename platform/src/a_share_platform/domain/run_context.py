"""Orthogonal data-qualification and deployment-stage run context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DataMode(str, Enum):
    """Qualification rules for data consumed by a run."""

    CURRENT_RESEARCH = "current_research"
    STRICT_HISTORICAL = "strict_historical"


class DeploymentStage(str, Enum):
    """Whether and how a run may affect an account."""

    RESEARCH = "research"
    SHADOW = "shadow"
    PAPER = "paper"
    LIMITED_LIVE = "limited_live"


class InvalidRunContextError(ValueError):
    """Raised when data qualification and deployment stage cannot be combined."""


_ALLOWED_STAGES_BY_DATA_MODE: dict[DataMode, frozenset[DeploymentStage]] = {
    DataMode.CURRENT_RESEARCH: frozenset(DeploymentStage),
    DataMode.STRICT_HISTORICAL: frozenset({DeploymentStage.RESEARCH}),
}


@dataclass(frozen=True)
class RunContext:
    """The two independent axes attached to every run.

    Strict historical data is only meaningful for historical research and
    backtests. It cannot be relabelled as a forward Shadow, Paper, or Live run.
    """

    data_mode: DataMode
    deployment_stage: DeploymentStage

    def __post_init__(self) -> None:
        data_mode = DataMode(self.data_mode)
        deployment_stage = DeploymentStage(self.deployment_stage)
        object.__setattr__(self, "data_mode", data_mode)
        object.__setattr__(self, "deployment_stage", deployment_stage)
        if deployment_stage not in _ALLOWED_STAGES_BY_DATA_MODE[data_mode]:
            raise InvalidRunContextError(
                f"data_mode={data_mode.value} cannot be combined with "
                f"deployment_stage={deployment_stage.value}"
            )
