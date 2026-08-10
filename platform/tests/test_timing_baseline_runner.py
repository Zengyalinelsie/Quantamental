import unittest
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from a_share_platform.adapters.memory.timing import InMemoryTimingForecastRepository
from a_share_platform.adapters.memory.timing_baseline import InMemoryTimingBaselineStore
from a_share_platform.application.timing_baseline import (
    TimingBaselineRequest,
    TimingBaselineRunner,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage
from a_share_platform.domain.timing import (
    PASSIVE_VOLATILITY_FORMULA_VERSION,
    BenchmarkCloseBatch,
    BenchmarkCloseObservation,
    TimingEstimateStatus,
    TimingModelLifecycle,
)

NOW = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
UNIVERSE_ID = "universe:000300:dataset:identity:v1:checkpoint"


def real_current_batch() -> BenchmarkCloseBatch:
    return BenchmarkCloseBatch(
        benchmark_id="index:000300",
        rows=tuple(
            BenchmarkCloseObservation(
                benchmark_id="index:000300",
                session_date=date(2026, 7, 21) + timedelta(days=index),
                unadjusted_close=Decimal(100 + index * index),
            )
            for index in range(21)
        ),
        provider_id="baostock_sdk",
        retrieved_at=NOW - timedelta(seconds=5),
        adjustment_mode="unadjusted",
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        data_mode=DataMode.CURRENT_RESEARCH,
    )


class FakeSource:
    provider_id = "baostock_sdk"

    def __init__(self, value: BenchmarkCloseBatch) -> None:
        self.value = value
        self.calls = 0

    def fetch_recent_closes(
        self,
        *,
        benchmark_id: str,
        end_session: date,
    ) -> BenchmarkCloseBatch:
        self.calls += 1
        self.assert_request = (benchmark_id, end_session)
        return self.value


def request() -> TimingBaselineRequest:
    return TimingBaselineRequest(
        benchmark_id="index:000300",
        universe_version_id=UNIVERSE_ID,
        effective_session=date(2026, 8, 10),
        target_volatility_ratio=Decimal("0.12"),
        code_version="git:test",
        environment_fingerprint="python:test",
    )


class TimingBaselineRunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.forecasts = InMemoryTimingForecastRepository()
        self.store = InMemoryTimingBaselineStore(
            known_universe_versions={("index:000300", UNIVERSE_ID)}
        )
        self.source = FakeSource(real_current_batch())
        self.runner = TimingBaselineRunner(
            source=self.source,
            store=self.store,
            forecast_repository=self.forecasts,
            clock=lambda: NOW,
        )

    def test_runner_persists_real_current_lineage_and_only_shadow_baseline_outputs(
        self,
    ) -> None:
        result = self.runner.run(request())
        forecast = result.forecast

        self.assertTrue(result.created)
        self.assertEqual(forecast.context.data_mode, DataMode.CURRENT_RESEARCH)
        self.assertEqual(forecast.context.deployment_stage, DeploymentStage.SHADOW)
        self.assertEqual(forecast.model_lifecycle, TimingModelLifecycle.BASELINE)
        self.assertIn(PASSIVE_VOLATILITY_FORMULA_VERSION, forecast.model_version_id)
        self.assertEqual(forecast.static_exposure_ratio, Decimal(1))
        self.assertEqual(
            forecast.passive_exposure_ratio,
            min(
                Decimal(1),
                request().target_volatility_ratio
                / forecast.passive_observed_volatility_ratio,
            ),
        )
        self.assertEqual(
            forecast.final_exposure_lower_ratio, forecast.passive_exposure_ratio
        )
        self.assertEqual(
            forecast.final_exposure_upper_ratio, forecast.passive_exposure_ratio
        )
        self.assertTrue(
            all(
                item.status is TimingEstimateStatus.UNAVAILABLE
                for item in forecast.horizon_forecasts
            )
        )
        self.assertEqual(forecast.risk_forecast.status, TimingEstimateStatus.UNAVAILABLE)
        self.assertEqual(
            forecast.active_adjustment.status, TimingEstimateStatus.UNAVAILABLE
        )
        self.assertEqual(forecast.input_trust_state, DataTrustState.NORMALIZED_CURRENT)

        self.assertEqual(len(self.store.datasets), 1)
        self.assertEqual(len(self.store.batches), 1)
        self.assertEqual(len(self.store.runs), 1)
        self.assertEqual(self.store.runs[0].context, forecast.context)
        self.assertEqual(self.store.runs[0].status.value, "succeeded")
        self.assertEqual(
            {(edge.upstream_id, edge.downstream_id, edge.relation) for edge in self.store.lineage},
            {
                (forecast.dataset_version_ids[0], forecast.run_id, "consumed_by"),
                (forecast.run_id, forecast.forecast_id, "produced"),
            },
        )

    def test_decision_time_is_observed_after_the_provider_retrieval_completes(self) -> None:
        gate_time = NOW - timedelta(seconds=10)
        decision_time = NOW
        clock_values = iter((gate_time, decision_time))
        source = FakeSource(
            BenchmarkCloseBatch(
                **{
                    **real_current_batch().__dict__,
                    "retrieved_at": NOW - timedelta(seconds=5),
                }
            )
        )
        runner = TimingBaselineRunner(
            source=source,
            store=self.store,
            forecast_repository=self.forecasts,
            clock=lambda: next(clock_values),
        )

        result = runner.run(request())

        self.assertEqual(result.forecast.data_cutoff_at, NOW - timedelta(seconds=5))
        self.assertEqual(result.forecast.decision_time, decision_time)

    def test_second_daily_run_returns_before_provider_or_persistence(self) -> None:
        first = self.runner.run(request())
        source_calls = self.source.calls
        dataset_count = len(self.store.datasets)
        run_count = len(self.store.runs)

        second = self.runner.run(request())

        self.assertFalse(second.created)
        self.assertEqual(second.forecast, first.forecast)
        self.assertEqual(self.source.calls, source_calls)
        self.assertEqual(len(self.store.datasets), dataset_count)
        self.assertEqual(len(self.store.runs), run_count)

    def test_unknown_or_mismatched_universe_fails_before_provider_access(self) -> None:
        invalid = TimingBaselineRequest(
            benchmark_id="index:000905",
            universe_version_id=UNIVERSE_ID,
            effective_session=date(2026, 8, 10),
            target_volatility_ratio=Decimal("0.12"),
            code_version="git:test",
            environment_fingerprint="python:test",
        )

        with self.assertRaisesRegex(ValueError, "universe version"):
            self.runner.run(invalid)
        self.assertEqual(self.source.calls, 0)

    def test_current_daily_bar_cannot_be_backdated_to_an_old_session(self) -> None:
        old = TimingBaselineRequest(
            benchmark_id="index:000300",
            universe_version_id=UNIVERSE_ID,
            effective_session=date(2026, 8, 9),
            target_volatility_ratio=Decimal("0.12"),
            code_version="git:test",
            environment_fingerprint="python:test",
        )

        with self.assertRaisesRegex(ValueError, "current Shanghai session"):
            self.runner.run(old)
        self.assertEqual(self.source.calls, 0)

    def test_daily_baseline_waits_until_the_close_is_complete(self) -> None:
        early = TimingBaselineRunner(
            source=self.source,
            store=self.store,
            forecast_repository=self.forecasts,
            clock=lambda: datetime(2026, 8, 10, 6, 59, tzinfo=UTC),
        )

        with self.assertRaisesRegex(ValueError, "after the A-share close"):
            early.run(request())
        self.assertEqual(self.source.calls, 0)


if __name__ == "__main__":
    unittest.main()
