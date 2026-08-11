"""Authoritative domain core for A-Share Platform Next."""

from .domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    ExpectedReturnCompileRequest,
    ExpectedReturnCompilerV0,
    ExpectedReturnResidual,
    ExpectedReturnUnavailable,
    InvestmentHorizon,
    InvestmentViewOutcome,
)
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
from .domain.signals import (
    SignalSnapshot,
    SignalSnapshotCompiler,
    SignalSnapshotCompileRequest,
    SignalSnapshotUnavailable,
)

__all__ = [
    "AuthorityRule",
    "DataMode",
    "DataQualityState",
    "DataTrustState",
    "DeploymentStage",
    "ExpectedReturnCalibrationRecord",
    "ExpectedReturnCompileRequest",
    "ExpectedReturnCompilerV0",
    "ExpectedReturnDistribution",
    "ExpectedReturnResidual",
    "ExpectedReturnUnavailable",
    "FactObservation",
    "FactSelection",
    "FinancialPeriodType",
    "InvalidRunContextError",
    "InvestmentComponent",
    "InvestmentComponentStatus",
    "InvestmentHorizon",
    "InvestmentView",
    "InvestmentViewOutcome",
    "PointInTimeConflictError",
    "RunContext",
    "SignalSnapshot",
    "SignalSnapshotCompileRequest",
    "SignalSnapshotCompiler",
    "SignalSnapshotUnavailable",
    "select_fact_as_of",
]
