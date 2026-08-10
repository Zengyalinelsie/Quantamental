"""Repository port for immutable timing forecasts."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from a_share_platform.domain.timing import TimingForecast


class TimingForecastRepository(Protocol):
    def save(self, value: TimingForecast) -> TimingForecast: ...

    def get(self, forecast_id: str) -> TimingForecast | None: ...

    def get_daily(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> TimingForecast | None: ...

    def list_forecasts(self) -> tuple[TimingForecast, ...]: ...
