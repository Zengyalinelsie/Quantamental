"""Repository port for immutable timing forecasts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Protocol

from a_share_platform.domain.governance import DatasetVersion, LineageEdge, RunRecord
from a_share_platform.domain.timing import BenchmarkCloseBatch, TimingForecast


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


class TimingBenchmarkSource(Protocol):
    provider_id: str

    def fetch_recent_closes(
        self,
        *,
        benchmark_id: str,
        end_session: date,
    ) -> BenchmarkCloseBatch: ...


class TimingBaselineStore(Protocol):
    def has_universe_version(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> bool: ...

    def register_dataset(
        self,
        value: DatasetVersion,
        *,
        metadata: Mapping[str, object],
    ) -> DatasetVersion: ...

    def save_benchmark_batch(
        self,
        dataset_version_id: str,
        batch: BenchmarkCloseBatch,
    ) -> None: ...

    def register_run(self, value: RunRecord) -> RunRecord: ...

    def register_lineage(self, value: LineageEdge) -> LineageEdge: ...
