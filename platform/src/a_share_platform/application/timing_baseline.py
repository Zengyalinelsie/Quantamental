"""Daily, idempotent passive timing baseline from real current index closes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from a_share_platform.application.timing_ledger import TimingShadowLedger
from a_share_platform.domain.governance import (
    DatasetVersion,
    LineageEdge,
    RunRecord,
    RunStatus,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.timing import (
    PASSIVE_VOLATILITY_FORMULA_VERSION,
    PASSIVE_VOLATILITY_LOOKBACK_RETURNS,
    ActiveTimingAdjustment,
    BenchmarkCloseBatch,
    HorizonReturnForecast,
    TimingEstimateStatus,
    TimingForecast,
    TimingModelLifecycle,
    TimingRiskForecast,
    estimate_passive_volatility,
    passive_volatility_exposure,
)
from a_share_platform.ports.timing import (
    TimingBaselineStore,
    TimingBenchmarkSource,
    TimingForecastRepository,
)

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CLOSE_COMPLETE_AFTER = time(15, 5)


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


@dataclass(frozen=True)
class TimingBaselineRequest:
    benchmark_id: str
    universe_version_id: str
    effective_session: date
    target_volatility_ratio: Decimal
    code_version: str
    environment_fingerprint: str

    def __post_init__(self) -> None:
        _text(self.benchmark_id, "benchmark_id")
        _text(self.universe_version_id, "universe_version_id")
        if self.benchmark_id not in {"index:000300", "index:000905"}:
            raise ValueError("benchmark_id must be a supported CSI benchmark")
        if not isinstance(self.effective_session, date) or isinstance(
            self.effective_session, datetime
        ):
            raise TypeError("effective_session must be a date")
        if not isinstance(self.target_volatility_ratio, Decimal):
            raise TypeError("target_volatility_ratio must be a Decimal")
        if (
            not self.target_volatility_ratio.is_finite()
            or self.target_volatility_ratio <= 0
        ):
            raise ValueError("target_volatility_ratio must be positive and finite")
        _text(self.code_version, "code_version")
        _text(self.environment_fingerprint, "environment_fingerprint")


@dataclass(frozen=True)
class TimingBaselineResult:
    forecast: TimingForecast
    created: bool


class TimingBaselineRunner:
    """Append one current-research shadow observation for a benchmark/session."""

    def __init__(
        self,
        *,
        source: TimingBenchmarkSource,
        store: TimingBaselineStore,
        forecast_repository: TimingForecastRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._source = source
        self._store = store
        self._forecasts = forecast_repository
        self._ledger = TimingShadowLedger(forecast_repository)
        self._clock = clock

    def run(self, request: TimingBaselineRequest) -> TimingBaselineResult:
        existing = self._forecasts.get_daily(
            benchmark_id=request.benchmark_id,
            universe_version_id=request.universe_version_id,
            effective_session=request.effective_session,
        )
        if existing is not None:
            if existing.passive_target_volatility_ratio != request.target_volatility_ratio:
                raise ValueError(
                    "daily timing baseline already exists with a different target volatility"
                )
            return TimingBaselineResult(existing, created=False)

        if not self._store.has_universe_version(
            benchmark_id=request.benchmark_id,
            universe_version_id=request.universe_version_id,
            effective_session=request.effective_session,
        ):
            raise ValueError("universe version does not match the requested benchmark")

        gate_time = self._clock()
        if gate_time.tzinfo is None or gate_time.utcoffset() is None:
            raise ValueError("timing baseline clock must be timezone-aware")
        local_now = gate_time.astimezone(_SHANGHAI)
        if request.effective_session != local_now.date():
            raise ValueError(
                "normalized_current timing baseline requires the current Shanghai session"
            )
        if local_now.timetz().replace(tzinfo=None) < _CLOSE_COMPLETE_AFTER:
            raise ValueError("timing baseline can run only after the A-share close is complete")

        batch = self._source.fetch_recent_closes(
            benchmark_id=request.benchmark_id,
            end_session=request.effective_session,
        )
        if batch.benchmark_id != request.benchmark_id:
            raise ValueError("benchmark source returned a different benchmark")
        if batch.effective_session != request.effective_session:
            raise ValueError("benchmark source did not return the requested complete session")
        if batch.provider_id != self._source.provider_id:
            raise ValueError("benchmark source provider lineage is inconsistent")
        decision_time = self._clock()
        if decision_time.tzinfo is None or decision_time.utcoffset() is None:
            raise ValueError("timing baseline clock must be timezone-aware")
        if decision_time < gate_time:
            raise ValueError("timing baseline clock cannot move backwards")
        if batch.retrieved_at > decision_time:
            raise ValueError("benchmark retrieval time cannot follow the run decision time")

        estimate = estimate_passive_volatility(batch)
        if estimate.annualized_volatility_ratio <= 0:
            raise ValueError("passive volatility is unavailable for a zero-variance window")
        dataset, metadata = self._dataset(batch)
        self._store.register_dataset(dataset, metadata=metadata)
        self._store.save_benchmark_batch(dataset.dataset_version_id, batch)

        suffix = dataset.content_hash.removeprefix("sha256:")[:16]
        run_id = (
            f"run:timing-shadow:{request.benchmark_id.removeprefix('index:')}:"
            f"{request.effective_session.isoformat()}:{suffix}"
        )
        forecast_id = (
            f"timing:{request.benchmark_id.removeprefix('index:')}:"
            f"{request.effective_session.isoformat()}:{suffix}"
        )
        context = RunContext(DataMode.CURRENT_RESEARCH, DeploymentStage.SHADOW)
        run = RunRecord(
            run_id=run_id,
            run_kind="timing_passive_volatility_baseline",
            status=RunStatus.SUCCEEDED,
            context=context,
            created_at=decision_time,
            code_version=request.code_version,
            environment_fingerprint=request.environment_fingerprint,
            finished_at=decision_time,
        )
        self._store.register_run(run)

        unavailable_reason = "active timing model is not implemented in P3"
        passive_exposure = passive_volatility_exposure(
            target_volatility_ratio=request.target_volatility_ratio,
            observed_volatility_ratio=estimate.annualized_volatility_ratio,
            maximum_exposure_ratio=Decimal(1),
        )
        forecast = TimingForecast(
            forecast_id=forecast_id,
            benchmark_id=request.benchmark_id,
            universe_version_id=request.universe_version_id,
            effective_session=request.effective_session,
            decision_time=decision_time,
            data_cutoff_at=batch.retrieved_at,
            created_at=decision_time,
            context=context,
            horizon_forecasts=tuple(
                HorizonReturnForecast(
                    horizon_trading_days=horizon,
                    status=TimingEstimateStatus.UNAVAILABLE,
                    status_reason=unavailable_reason,
                )
                for horizon in (1, 5, 20, 60)
            ),
            risk_forecast=TimingRiskForecast(
                status=TimingEstimateStatus.UNAVAILABLE,
                status_reason=unavailable_reason,
            ),
            static_exposure_ratio=Decimal(1),
            passive_exposure_ratio=passive_exposure,
            passive_target_volatility_ratio=request.target_volatility_ratio,
            passive_observed_volatility_ratio=estimate.annualized_volatility_ratio,
            passive_lookback_sessions=PASSIVE_VOLATILITY_LOOKBACK_RETURNS,
            active_adjustment=ActiveTimingAdjustment(
                status=TimingEstimateStatus.UNAVAILABLE,
                status_reason=unavailable_reason,
            ),
            final_exposure_lower_ratio=passive_exposure,
            final_exposure_upper_ratio=passive_exposure,
            model_version_id=(
                "timing-model:passive-volatility:"
                + PASSIVE_VOLATILITY_FORMULA_VERSION
            ),
            model_lifecycle=TimingModelLifecycle.BASELINE,
            run_id=run_id,
            approval_scope="shadow_baseline_only",
            dataset_version_ids=(dataset.dataset_version_id,),
            input_trust_state=batch.trust_state,
        )
        stored = self._ledger.append_baseline(forecast)
        self._store.register_lineage(
            LineageEdge(dataset.dataset_version_id, run_id, "consumed_by")
        )
        self._store.register_lineage(LineageEdge(run_id, forecast_id, "produced"))
        return TimingBaselineResult(stored, created=True)

    @staticmethod
    def _dataset(batch: BenchmarkCloseBatch) -> tuple[DatasetVersion, dict[str, object]]:
        document = {
            "benchmark_id": batch.benchmark_id,
            "provider_id": batch.provider_id,
            "retrieved_at": batch.retrieved_at.isoformat(),
            "adjustment_mode": batch.adjustment_mode,
            "trust_state": batch.trust_state.value,
            "data_mode": batch.data_mode.value,
            "rows": [
                {
                    "session_date": row.session_date.isoformat(),
                    "unadjusted_close": str(row.unadjusted_close),
                }
                for row in batch.rows
            ],
        }
        payload = json.dumps(
            document,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        dataset_id = (
            f"dataset:timing-benchmark:{batch.benchmark_id.removeprefix('index:')}:"
            f"{batch.effective_session.isoformat()}:{digest[:16]}"
        )
        return (
            DatasetVersion(
                dataset_version_id=dataset_id,
                content_hash=f"sha256:{digest}",
                created_at=batch.retrieved_at,
                schema_version="timing-benchmark-bars:v1",
            ),
            {"manifest": document},
        )
