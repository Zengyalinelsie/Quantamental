"""Immutable timing forecasts and passive shadow baselines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

from .pit import DataTrustState
from .run_context import RunContext

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_REQUIRED_HORIZONS = (1, 5, 20, 60)
_ZERO = Decimal(0)
_ONE = Decimal(1)


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _optional_decimal(value: Decimal | None, field_name: str) -> Decimal | None:
    return None if value is None else _decimal(value, field_name)


def _ratio(value: Decimal, field_name: str) -> Decimal:
    value = _decimal(value, field_name)
    if not _ZERO <= value <= _ONE:
        raise ValueError(f"{field_name} must be in [0, 1]")
    return value


class TimingEstimateStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


class TimingModelLifecycle(str, Enum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    APPROVED = "approved"
    RETIRED = "retired"


@dataclass(frozen=True)
class HorizonReturnForecast:
    horizon_trading_days: int
    status: TimingEstimateStatus
    up_probability: Decimal | None = None
    expected_return_ratio: Decimal | None = None
    p10_return_ratio: Decimal | None = None
    p50_return_ratio: Decimal | None = None
    p90_return_ratio: Decimal | None = None
    status_reason: str | None = None

    def __post_init__(self) -> None:
        if self.horizon_trading_days not in _REQUIRED_HORIZONS:
            raise ValueError("horizon_trading_days must be one of 1, 5, 20, and 60")
        status = TimingEstimateStatus(self.status)
        object.__setattr__(self, "status", status)
        numeric_names = (
            "up_probability",
            "expected_return_ratio",
            "p10_return_ratio",
            "p50_return_ratio",
            "p90_return_ratio",
        )
        numeric_values = tuple(
            _optional_decimal(getattr(self, name), name) for name in numeric_names
        )
        if status is TimingEstimateStatus.UNAVAILABLE:
            if any(value is not None for value in numeric_values):
                raise ValueError("unavailable horizon forecast must not carry numeric values")
            _require_text(self.status_reason or "", "status_reason")
            return
        if any(value is None for value in numeric_values):
            raise ValueError("quantified horizon forecast requires its complete distribution")
        probability, point, p10, p50, p90 = numeric_values
        assert probability is not None
        assert point is not None
        assert p10 is not None
        assert p50 is not None
        assert p90 is not None
        _ratio(probability, "up_probability")
        if not p10 <= p50 <= p90:
            raise ValueError("return percentiles must satisfy p10 <= p50 <= p90")
        if not p10 <= point <= p90:
            raise ValueError("expected return must lie inside [p10, p90]")
        if self.status_reason is not None:
            raise ValueError("quantified horizon forecast must not have an unavailable reason")


@dataclass(frozen=True)
class TimingRiskForecast:
    status: TimingEstimateStatus
    annualized_volatility_ratio: Decimal | None = None
    maximum_drawdown_ratio: Decimal | None = None
    tail_loss_ratio: Decimal | None = None
    status_reason: str | None = None

    def __post_init__(self) -> None:
        status = TimingEstimateStatus(self.status)
        object.__setattr__(self, "status", status)
        numeric = tuple(
            _optional_decimal(getattr(self, name), name)
            for name in (
                "annualized_volatility_ratio",
                "maximum_drawdown_ratio",
                "tail_loss_ratio",
            )
        )
        if status is TimingEstimateStatus.UNAVAILABLE:
            if any(value is not None for value in numeric):
                raise ValueError("unavailable risk forecast must not carry numeric values")
            _require_text(self.status_reason or "", "status_reason")
            return
        if all(value is None for value in numeric):
            raise ValueError("quantified risk forecast requires at least one risk estimate")
        if any(value is not None and value < _ZERO for value in numeric):
            raise ValueError("risk ratios cannot be negative")
        if self.status_reason is not None:
            raise ValueError("quantified risk forecast must not have an unavailable reason")


@dataclass(frozen=True)
class ActiveTimingAdjustment:
    status: TimingEstimateStatus
    point_exposure_delta: Decimal | None = None
    lower_exposure_delta: Decimal | None = None
    upper_exposure_delta: Decimal | None = None
    status_reason: str | None = None

    def __post_init__(self) -> None:
        status = TimingEstimateStatus(self.status)
        object.__setattr__(self, "status", status)
        numeric = tuple(
            _optional_decimal(getattr(self, name), name)
            for name in (
                "point_exposure_delta",
                "lower_exposure_delta",
                "upper_exposure_delta",
            )
        )
        if status is TimingEstimateStatus.UNAVAILABLE:
            if any(value is not None for value in numeric):
                raise ValueError("unavailable active adjustment must not carry numeric values")
            _require_text(self.status_reason or "", "status_reason")
            return
        if any(value is None for value in numeric):
            raise ValueError("quantified active adjustment requires point and confidence bounds")
        point, lower, upper = numeric
        assert point is not None
        assert lower is not None
        assert upper is not None
        if not lower <= point <= upper:
            raise ValueError("active adjustment must satisfy lower <= point <= upper")
        if self.status_reason is not None:
            raise ValueError("quantified active adjustment must not have an unavailable reason")


def passive_volatility_exposure(
    *,
    target_volatility_ratio: Decimal,
    observed_volatility_ratio: Decimal,
    maximum_exposure_ratio: Decimal,
) -> Decimal:
    """Return an unlevered volatility-target exposure using exact decimals."""

    target = _decimal(target_volatility_ratio, "target_volatility_ratio")
    observed = _decimal(observed_volatility_ratio, "observed_volatility_ratio")
    maximum = _ratio(maximum_exposure_ratio, "maximum_exposure_ratio")
    if target <= _ZERO:
        raise ValueError("target_volatility_ratio must be positive")
    if observed <= _ZERO:
        raise ValueError("observed_volatility_ratio must be positive")
    return min(maximum, target / observed)


@dataclass(frozen=True)
class TimingForecast:
    forecast_id: str
    benchmark_id: str
    universe_version_id: str
    effective_session: date
    decision_time: datetime
    data_cutoff_at: datetime
    created_at: datetime
    context: RunContext
    horizon_forecasts: tuple[HorizonReturnForecast, ...]
    risk_forecast: TimingRiskForecast
    static_exposure_ratio: Decimal
    passive_exposure_ratio: Decimal
    passive_target_volatility_ratio: Decimal
    passive_observed_volatility_ratio: Decimal
    passive_lookback_sessions: int
    active_adjustment: ActiveTimingAdjustment
    final_exposure_lower_ratio: Decimal
    final_exposure_upper_ratio: Decimal
    model_version_id: str
    model_lifecycle: TimingModelLifecycle
    run_id: str
    approval_scope: str
    dataset_version_ids: tuple[str, ...]
    input_trust_state: DataTrustState

    def __post_init__(self) -> None:
        for name in (
            "forecast_id",
            "benchmark_id",
            "universe_version_id",
            "model_version_id",
            "run_id",
            "approval_scope",
        ):
            _require_text(getattr(self, name), name)
        if not isinstance(self.effective_session, date) or isinstance(
            self.effective_session, datetime
        ):
            raise TypeError("effective_session must be a date")
        decision_time = _require_aware(self.decision_time, "decision_time")
        data_cutoff_at = _require_aware(self.data_cutoff_at, "data_cutoff_at")
        created_at = _require_aware(self.created_at, "created_at")
        if data_cutoff_at > decision_time:
            raise ValueError("data_cutoff_at cannot follow decision_time")
        if created_at < decision_time:
            raise ValueError("created_at cannot precede decision_time")
        if decision_time.astimezone(_SHANGHAI).date() != self.effective_session:
            raise ValueError("effective_session must match the Asia/Shanghai decision date")
        if not isinstance(self.context, RunContext):
            raise TypeError("context must be a RunContext")

        horizons = tuple(self.horizon_forecasts)
        if tuple(item.horizon_trading_days for item in horizons) != _REQUIRED_HORIZONS:
            raise ValueError("horizon forecasts must contain 1, 5, 20, and 60 in order")
        object.__setattr__(self, "horizon_forecasts", horizons)
        if not isinstance(self.risk_forecast, TimingRiskForecast):
            raise TypeError("risk_forecast must be a TimingRiskForecast")
        if not isinstance(self.active_adjustment, ActiveTimingAdjustment):
            raise TypeError("active_adjustment must be an ActiveTimingAdjustment")

        static = _ratio(self.static_exposure_ratio, "static_exposure_ratio")
        passive = _ratio(self.passive_exposure_ratio, "passive_exposure_ratio")
        target = _decimal(
            self.passive_target_volatility_ratio,
            "passive_target_volatility_ratio",
        )
        observed = _decimal(
            self.passive_observed_volatility_ratio,
            "passive_observed_volatility_ratio",
        )
        if target <= _ZERO or observed <= _ZERO:
            raise ValueError("passive volatility ratios must be positive")
        if type(self.passive_lookback_sessions) is not int or self.passive_lookback_sessions <= 1:
            raise ValueError("passive_lookback_sessions must be an integer greater than one")
        lower = _ratio(self.final_exposure_lower_ratio, "final_exposure_lower_ratio")
        upper = _ratio(self.final_exposure_upper_ratio, "final_exposure_upper_ratio")
        if lower > upper:
            raise ValueError("final exposure must satisfy lower <= upper")
        for name, value in (
            ("static_exposure_ratio", static),
            ("passive_exposure_ratio", passive),
            ("passive_target_volatility_ratio", target),
            ("passive_observed_volatility_ratio", observed),
            ("final_exposure_lower_ratio", lower),
            ("final_exposure_upper_ratio", upper),
        ):
            object.__setattr__(self, name, value)

        object.__setattr__(self, "model_lifecycle", TimingModelLifecycle(self.model_lifecycle))
        datasets = tuple(self.dataset_version_ids)
        if not datasets or any(not str(item or "").strip() for item in datasets):
            raise ValueError("dataset_version_ids must contain non-empty identifiers")
        if len(datasets) != len(set(datasets)):
            raise ValueError("dataset_version_ids must be unique")
        object.__setattr__(self, "dataset_version_ids", datasets)
        trust = DataTrustState(self.input_trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw input is not eligible for a timing forecast")
        object.__setattr__(self, "input_trust_state", trust)
