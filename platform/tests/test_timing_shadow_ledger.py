import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from a_share_platform.adapters.memory.timing import InMemoryTimingForecastRepository
from a_share_platform.application.timing_ledger import TimingShadowLedger
from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.timing import (
    ActiveTimingAdjustment,
    HorizonReturnForecast,
    TimingEstimateStatus,
    TimingForecast,
    TimingModelLifecycle,
    TimingRiskForecast,
    passive_volatility_exposure,
)

DECISION_TIME = datetime(2026, 8, 10, 7, 0, tzinfo=UTC)
CREATED_AT = DECISION_TIME + timedelta(minutes=5)


def unavailable_horizons() -> tuple[HorizonReturnForecast, ...]:
    return tuple(
        HorizonReturnForecast(
            horizon_trading_days=horizon,
            status=TimingEstimateStatus.UNAVAILABLE,
            status_reason="active timing model is not implemented in P3",
        )
        for horizon in (1, 5, 20, 60)
    )


def baseline_forecast(**overrides: object) -> TimingForecast:
    values: dict[str, object] = {
        "forecast_id": "timing:000300:2026-08-10:static-vol-v1",
        "benchmark_id": "index:000300",
        "universe_version_id": "universe:csi300:2026-08-10",
        "effective_session": date(2026, 8, 10),
        "decision_time": DECISION_TIME,
        "data_cutoff_at": DECISION_TIME - timedelta(minutes=1),
        "created_at": CREATED_AT,
        "context": RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.SHADOW),
        "horizon_forecasts": unavailable_horizons(),
        "risk_forecast": TimingRiskForecast(
            status=TimingEstimateStatus.UNAVAILABLE,
            status_reason="P3 records baselines, not an active risk forecast",
        ),
        "static_exposure_ratio": Decimal(1),
        "passive_exposure_ratio": Decimal("0.60"),
        "passive_target_volatility_ratio": Decimal("0.12"),
        "passive_observed_volatility_ratio": Decimal("0.20"),
        "passive_lookback_sessions": 20,
        "active_adjustment": ActiveTimingAdjustment(
            status=TimingEstimateStatus.UNAVAILABLE,
            status_reason="active timing model is not implemented in P3",
        ),
        "final_exposure_lower_ratio": Decimal("0.60"),
        "final_exposure_upper_ratio": Decimal("0.60"),
        "model_version_id": "timing-model:static-vol-baseline:v1",
        "model_lifecycle": TimingModelLifecycle.BASELINE,
        "run_id": "run:timing-shadow:2026-08-10",
        "approval_scope": "shadow_baseline_only",
        "dataset_version_ids": ("dataset:csi300-bars:2026-08-10",),
        "input_trust_state": DataTrustState.NORMALIZED_CURRENT,
    }
    values.update(overrides)
    return TimingForecast(**values)  # type: ignore[arg-type]


class TimingForecastContractTest(unittest.TestCase):
    def test_p3_baseline_is_immutable_and_keeps_active_outputs_explicitly_unavailable(self) -> None:
        value = baseline_forecast()

        self.assertEqual(
            tuple(item.horizon_trading_days for item in value.horizon_forecasts),
            (1, 5, 20, 60),
        )
        self.assertEqual(value.active_adjustment.status, TimingEstimateStatus.UNAVAILABLE)
        self.assertEqual(value.final_exposure_lower_ratio, value.passive_exposure_ratio)
        with self.assertRaises(FrozenInstanceError):
            value.passive_exposure_ratio = Decimal("0.50")  # type: ignore[misc]

    def test_all_required_horizons_must_exist_even_before_an_active_model_exists(self) -> None:
        with self.assertRaisesRegex(ValueError, "1, 5, 20, and 60"):
            baseline_forecast(horizon_forecasts=unavailable_horizons()[:-1])

    def test_unavailable_estimates_cannot_carry_numeric_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "unavailable.*numeric"):
            HorizonReturnForecast(
                horizon_trading_days=1,
                status=TimingEstimateStatus.UNAVAILABLE,
                up_probability=Decimal("0.5"),
                status_reason="not produced",
            )

    def test_cutoff_and_creation_times_cannot_claim_future_knowledge(self) -> None:
        with self.assertRaisesRegex(ValueError, "data_cutoff_at"):
            baseline_forecast(data_cutoff_at=DECISION_TIME + timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "created_at"):
            baseline_forecast(created_at=DECISION_TIME - timedelta(seconds=1))

    def test_passive_volatility_baseline_uses_decimal_and_caps_at_static_exposure(self) -> None:
        self.assertEqual(
            passive_volatility_exposure(
                target_volatility_ratio=Decimal("0.12"),
                observed_volatility_ratio=Decimal("0.20"),
                maximum_exposure_ratio=Decimal(1),
            ),
            Decimal("0.60"),
        )
        self.assertEqual(
            passive_volatility_exposure(
                target_volatility_ratio=Decimal("0.12"),
                observed_volatility_ratio=Decimal("0.06"),
                maximum_exposure_ratio=Decimal(1),
            ),
            Decimal(1),
        )
        with self.assertRaisesRegex(TypeError, "Decimal"):
            passive_volatility_exposure(  # type: ignore[arg-type]
                target_volatility_ratio=0.12,
                observed_volatility_ratio=Decimal("0.20"),
                maximum_exposure_ratio=Decimal(1),
            )


class TimingShadowLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryTimingForecastRepository()
        self.ledger = TimingShadowLedger(self.repository)

    def test_append_accepts_only_current_research_shadow_baselines(self) -> None:
        value = baseline_forecast()
        self.assertIs(self.ledger.append_baseline(value), value)
        self.assertIs(self.ledger.append_baseline(value), value)

        invalid_contexts = (
            RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.RESEARCH),
            RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.PAPER),
            RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH),
        )
        for context in invalid_contexts:
            with (
                self.subTest(context=context),
                self.assertRaisesRegex(ValueError, "current_research.*shadow"),
            ):
                self.ledger.append_baseline(
                    replace(
                        value,
                        forecast_id=f"{value.forecast_id}:{context.data_mode.value}:"
                        f"{context.deployment_stage.value}",
                        context=context,
                    )
                )

    def test_baseline_ledger_rejects_active_numbers_and_non_baseline_lifecycle(self) -> None:
        active = ActiveTimingAdjustment(
            status=TimingEstimateStatus.QUANTIFIED,
            point_exposure_delta=Decimal("0.10"),
            lower_exposure_delta=Decimal("0.05"),
            upper_exposure_delta=Decimal("0.15"),
        )
        with self.assertRaisesRegex(ValueError, "active adjustment.*unavailable"):
            self.ledger.append_baseline(
                baseline_forecast(
                    active_adjustment=active,
                    final_exposure_lower_ratio=Decimal("0.65"),
                    final_exposure_upper_ratio=Decimal("0.75"),
                )
            )
        with self.assertRaisesRegex(ValueError, "baseline lifecycle"):
            self.ledger.append_baseline(
                baseline_forecast(model_lifecycle=TimingModelLifecycle.CANDIDATE)
            )

    def test_daily_key_and_identifier_are_immutable(self) -> None:
        value = baseline_forecast()
        self.ledger.append_baseline(value)

        with self.assertRaises(VersionConflictError):
            self.ledger.append_baseline(
                replace(
                    value,
                    passive_exposure_ratio=Decimal("0.55"),
                    passive_target_volatility_ratio=Decimal("0.11"),
                    final_exposure_lower_ratio=Decimal("0.55"),
                    final_exposure_upper_ratio=Decimal("0.55"),
                )
            )
        with self.assertRaisesRegex(VersionConflictError, "daily timing baseline"):
            self.ledger.append_baseline(
                replace(value, forecast_id="timing:000300:2026-08-10:another-id")
            )


if __name__ == "__main__":
    unittest.main()
