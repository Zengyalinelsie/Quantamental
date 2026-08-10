"""Authoritative domain core for A-Share Platform Next."""

from .domain.investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from .domain.pit import (
    DataTrustState,
    FactObservation,
    PointInTimeConflictError,
    select_fact_as_of,
)
from .domain.run_context import DataMode, DeploymentStage, InvalidRunContextError, RunContext

__all__ = [
    "DataMode",
    "DataTrustState",
    "DeploymentStage",
    "ExpectedReturnDistribution",
    "FactObservation",
    "InvalidRunContextError",
    "InvestmentComponent",
    "InvestmentComponentStatus",
    "InvestmentView",
    "PointInTimeConflictError",
    "RunContext",
    "select_fact_as_of",
]
