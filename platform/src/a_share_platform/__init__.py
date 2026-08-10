"""Authoritative domain core for A-Share Platform Next."""

from .domain.investment_view import ExpectedReturnDistribution, InvestmentComponent, InvestmentView
from .domain.pit import (
    DataTrustState,
    DataUseCase,
    FactObservation,
    PointInTimeConflictError,
    select_fact_as_of,
)

__all__ = [
    "DataTrustState",
    "DataUseCase",
    "ExpectedReturnDistribution",
    "FactObservation",
    "InvestmentComponent",
    "InvestmentView",
    "PointInTimeConflictError",
    "select_fact_as_of",
]
