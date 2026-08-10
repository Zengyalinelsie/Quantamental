import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from a_share_platform.adapters.postgres.timing import PostgresTimingForecastRepository
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.timing import (
    ActiveTimingAdjustment,
    HorizonReturnForecast,
    TimingEstimateStatus,
    TimingForecast,
    TimingModelLifecycle,
    TimingRiskForecast,
)

DECISION_TIME = datetime(2026, 8, 10, 7, 0, tzinfo=UTC)


def forecast() -> TimingForecast:
    return TimingForecast(
        forecast_id="timing:000300:2026-08-10:static-vol-v1",
        benchmark_id="index:000300",
        universe_version_id="universe:csi300:2026-08-10",
        effective_session=date(2026, 8, 10),
        decision_time=DECISION_TIME,
        data_cutoff_at=DECISION_TIME - timedelta(minutes=1),
        created_at=DECISION_TIME + timedelta(minutes=5),
        context=RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.SHADOW),
        horizon_forecasts=tuple(
            HorizonReturnForecast(
                horizon_trading_days=item,
                status=TimingEstimateStatus.UNAVAILABLE,
                status_reason="active forecast unavailable in P3",
            )
            for item in (1, 5, 20, 60)
        ),
        risk_forecast=TimingRiskForecast(
            status=TimingEstimateStatus.UNAVAILABLE,
            status_reason="active risk forecast unavailable in P3",
        ),
        static_exposure_ratio=Decimal(1),
        passive_exposure_ratio=Decimal("0.6"),
        passive_target_volatility_ratio=Decimal("0.12"),
        passive_observed_volatility_ratio=Decimal("0.2"),
        passive_lookback_sessions=20,
        active_adjustment=ActiveTimingAdjustment(
            status=TimingEstimateStatus.UNAVAILABLE,
            status_reason="active adjustment unavailable in P3",
        ),
        final_exposure_lower_ratio=Decimal("0.6"),
        final_exposure_upper_ratio=Decimal("0.6"),
        model_version_id="timing-model:static-vol-baseline:v1",
        model_lifecycle=TimingModelLifecycle.BASELINE,
        run_id="run:timing-shadow:2026-08-10",
        approval_scope="shadow_baseline_only",
        dataset_version_ids=("dataset:csi300-bars:2026-08-10",),
        input_trust_state=DataTrustState.NORMALIZED_CURRENT,
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        *,
        insert_row: tuple[object, ...] | None = None,
    ) -> None:
        self.rows = rows or []
        self.insert_row = insert_row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if query.lstrip().startswith("INSERT") and self.insert_row is not None:
            self.rows = [self.insert_row]
        return FakeResult(self.rows if query.lstrip().startswith("SELECT") else [])


class PostgresTimingForecastRepositoryTest(unittest.TestCase):
    def test_insert_is_append_only_and_preserves_context_and_decimal_values(self) -> None:
        value = forecast()
        connection = FakeConnection(
            insert_row=PostgresTimingForecastRepository.to_row(value)
        )
        repository = PostgresTimingForecastRepository(connection)

        repository.save(value)

        query, params = next(
            (query, params)
            for query, params in connection.calls
            if query.lstrip().startswith("INSERT")
        )
        self.assertIn("INSERT INTO timing_forecasts", query)
        self.assertIn("ON CONFLICT (forecast_id) DO NOTHING", query)
        self.assertNotIn("UPDATE", query)
        self.assertEqual(params[0], value.forecast_id)
        self.assertEqual(params[7:9], ("current_research", "shadow"))
        self.assertEqual(params[12], "0.6")
        self.assertEqual(params[24], "normalized_current")

    def test_round_trip_restores_the_complete_immutable_forecast(self) -> None:
        value = forecast()
        row = PostgresTimingForecastRepository.to_row(value)
        repository = PostgresTimingForecastRepository(FakeConnection([row]))

        self.assertEqual(repository.get(value.forecast_id), value)

    def test_daily_lookup_uses_benchmark_universe_and_session(self) -> None:
        value = forecast()
        connection = FakeConnection()
        repository = PostgresTimingForecastRepository(connection)

        repository.get_daily(
            benchmark_id=value.benchmark_id,
            universe_version_id=value.universe_version_id,
            effective_session=value.effective_session,
        )

        query, params = connection.calls[-1]
        self.assertIn("benchmark_id = %s", query)
        self.assertIn("universe_version_id = %s", query)
        self.assertIn("effective_session = %s", query)
        self.assertEqual(
            params,
            (value.benchmark_id, value.universe_version_id, value.effective_session),
        )


if __name__ == "__main__":
    unittest.main()
