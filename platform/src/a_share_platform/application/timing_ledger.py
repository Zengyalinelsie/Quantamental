"""Append-only P3 timing baseline use case."""

from __future__ import annotations

from decimal import Decimal

from a_share_platform.domain.run_context import DataMode, DeploymentStage
from a_share_platform.domain.timing import (
    TimingEstimateStatus,
    TimingForecast,
    TimingModelLifecycle,
    passive_volatility_exposure,
)
from a_share_platform.ports.timing import TimingForecastRepository


class TimingShadowLedger:
    def __init__(self, repository: TimingForecastRepository) -> None:
        self._repository = repository

    def append_baseline(self, value: TimingForecast) -> TimingForecast:
        if (
            value.context.data_mode is not DataMode.CURRENT_RESEARCH
            or value.context.deployment_stage is not DeploymentStage.SHADOW
        ):
            raise ValueError("P3 timing baseline requires current_research + shadow")
        if value.model_lifecycle is not TimingModelLifecycle.BASELINE:
            raise ValueError("P3 timing shadow record requires baseline lifecycle")
        if value.active_adjustment.status is not TimingEstimateStatus.UNAVAILABLE:
            raise ValueError("P3 timing baseline active adjustment must remain unavailable")
        if any(
            item.status is not TimingEstimateStatus.UNAVAILABLE
            for item in value.horizon_forecasts
        ):
            raise ValueError("P3 timing baseline horizon forecasts must remain unavailable")
        if value.risk_forecast.status is not TimingEstimateStatus.UNAVAILABLE:
            raise ValueError("P3 timing baseline risk forecast must remain unavailable")
        if value.static_exposure_ratio != Decimal(1):
            raise ValueError("P3 static full-investment baseline must equal 1")
        expected_passive = passive_volatility_exposure(
            target_volatility_ratio=value.passive_target_volatility_ratio,
            observed_volatility_ratio=value.passive_observed_volatility_ratio,
            maximum_exposure_ratio=value.static_exposure_ratio,
        )
        if value.passive_exposure_ratio != expected_passive:
            raise ValueError("passive exposure does not match the volatility baseline formula")
        if (
            value.final_exposure_lower_ratio != value.passive_exposure_ratio
            or value.final_exposure_upper_ratio != value.passive_exposure_ratio
        ):
            raise ValueError(
                "P3 final exposure must equal the passive baseline while active timing is unavailable"
            )
        if value.approval_scope != "shadow_baseline_only":
            raise ValueError("P3 timing baseline approval_scope must be shadow_baseline_only")
        return self._repository.save(value)
