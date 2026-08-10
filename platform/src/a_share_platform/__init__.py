"""Authoritative domain core for A-Share Platform Next."""

from .domain.investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from .domain.pit import (
    AuthorityRule,
    DataQualityState,
    DataTrustState,
    FactObservation,
    FactSelection,
    FinancialPeriodType,
    PointInTimeConflictError,
    select_fact_as_of,
)
from .domain.run_context import DataMode, DeploymentStage, InvalidRunContextError, RunContext

__all__ = [
    "AuthorityRule",
    "DataMode",
    "DataQualityState",
    "DataTrustState",
    "DeploymentStage",
    "ExpectedReturnDistribution",
    "FactObservation",
    "FactSelection",
    "FinancialPeriodType",
    "InvalidRunContextError",
    "InvestmentComponent",
    "InvestmentComponentStatus",
    "InvestmentView",
    "PointInTimeConflictError",
    "RunContext",
    "select_fact_as_of",
]
