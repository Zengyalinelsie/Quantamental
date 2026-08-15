"""In-memory immutable timing forecast repository."""

from __future__ import annotations

from datetime import date
from typing import Never

from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.timing import TimingForecast
from a_share_platform.ports.timing import TimingForecastStoreUnavailable


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


class UnavailableTimingForecastRepository:
    """Fail-closed stand-in when no timing persistence is configured.

    An unconfigured runtime must not look like an empty ledger: "no store" and
    "no records" are different answers, and only the first one is a blocker.
    """

    def __init__(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("unavailable timing store reason must not be empty")
        self._reason = reason

    def _raise(self) -> Never:
        raise TimingForecastStoreUnavailable(self._reason)

    def save(self, value: TimingForecast) -> TimingForecast:
        del value
        self._raise()

    def get(self, forecast_id: str) -> TimingForecast | None:
        del forecast_id
        self._raise()

    def get_daily(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> TimingForecast | None:
        del benchmark_id, universe_version_id, effective_session
        self._raise()

    def list_forecasts(self) -> tuple[TimingForecast, ...]:
        self._raise()


__all__ = [
    "InMemoryTimingForecastRepository",
    "UnavailableTimingForecastRepository",
]
