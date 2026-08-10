"""In-memory immutable timing forecast repository."""

from __future__ import annotations

from datetime import date

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.timing import TimingForecast


class InMemoryTimingForecastRepository:
    def __init__(self) -> None:
        self._values: dict[str, TimingForecast] = {}
        self._daily: dict[tuple[str, str, date], str] = {}

    def save(self, value: TimingForecast) -> TimingForecast:
        existing = self._values.get(value.forecast_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable timing forecast identifier conflict: {value.forecast_id}"
                )
            return existing
        key = (value.benchmark_id, value.universe_version_id, value.effective_session)
        owner = self._daily.get(key)
        if owner is not None:
            raise VersionConflictError(
                "daily timing baseline already exists for "
                f"benchmark={value.benchmark_id}, universe={value.universe_version_id}, "
                f"session={value.effective_session.isoformat()}: {owner}"
            )
        self._values[value.forecast_id] = value
        self._daily[key] = value.forecast_id
        return value

    def get(self, forecast_id: str) -> TimingForecast | None:
        return self._values.get(forecast_id)

    def get_daily(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> TimingForecast | None:
        identifier = self._daily.get(
            (benchmark_id, universe_version_id, effective_session)
        )
        return None if identifier is None else self._values[identifier]

    def list_forecasts(self) -> tuple[TimingForecast, ...]:
        return tuple(self._values.values())
