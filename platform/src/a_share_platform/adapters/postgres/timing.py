"""PostgreSQL adapter for the append-only timing forecast ledger."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

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
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as error:
        raise ValueError(f"stored {field_name} is not a decimal") from error


def _horizon_document(value: HorizonReturnForecast) -> dict[str, object]:
    return {
        "horizon_trading_days": value.horizon_trading_days,
        "status": value.status.value,
        "up_probability": _decimal_text(value.up_probability),
        "expected_return_ratio": _decimal_text(value.expected_return_ratio),
        "p10_return_ratio": _decimal_text(value.p10_return_ratio),
        "p50_return_ratio": _decimal_text(value.p50_return_ratio),
        "p90_return_ratio": _decimal_text(value.p90_return_ratio),
        "status_reason": value.status_reason,
    }


def _risk_document(value: TimingRiskForecast) -> dict[str, object]:
    return {
        "status": value.status.value,
        "annualized_volatility_ratio": _decimal_text(value.annualized_volatility_ratio),
        "maximum_drawdown_ratio": _decimal_text(value.maximum_drawdown_ratio),
        "tail_loss_ratio": _decimal_text(value.tail_loss_ratio),
        "status_reason": value.status_reason,
    }


def _active_document(value: ActiveTimingAdjustment) -> dict[str, object]:
    return {
        "status": value.status.value,
        "point_exposure_delta": _decimal_text(value.point_exposure_delta),
        "lower_exposure_delta": _decimal_text(value.lower_exposure_delta),
        "upper_exposure_delta": _decimal_text(value.upper_exposure_delta),
        "status_reason": value.status_reason,
    }


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class PostgresTimingForecastRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save(self, value: TimingForecast) -> TimingForecast:
        existing = self.get(value.forecast_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable timing forecast identifier conflict: {value.forecast_id}"
                )
            return existing
        row = self.to_row(value)
        params = tuple(
            _json_parameter(item) if index in {9, 10, 16, 23} else item
            for index, item in enumerate(row)
        )
        self._connection.execute(
            """
            INSERT INTO research.timing_forecasts (
                forecast_id, benchmark_id, universe_version_id, effective_session,
                decision_time, data_cutoff_at, created_at, data_mode, deployment_stage,
                horizon_forecasts, risk_forecast, static_exposure_ratio,
                passive_exposure_ratio, passive_target_volatility_ratio,
                passive_observed_volatility_ratio, passive_lookback_sessions,
                active_adjustment, final_exposure_lower_ratio, final_exposure_upper_ratio,
                model_version_id, model_lifecycle, run_id, approval_scope,
                dataset_version_ids, input_trust_state
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ON CONFLICT (forecast_id) DO NOTHING
            """,
            params,
        )
        stored = self.get(value.forecast_id)
        if stored is None:
            raise RuntimeError("timing forecast insert was not observable")
        if stored != value:
            raise VersionConflictError(
                f"immutable timing forecast identifier conflict: {value.forecast_id}"
            )
        return stored

    def get(self, forecast_id: str) -> TimingForecast | None:
        row = self._connection.execute(
            self._select() + " WHERE forecast_id = %s",
            (forecast_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def get_daily(
        self,
        *,
        benchmark_id: str,
        universe_version_id: str,
        effective_session: date,
    ) -> TimingForecast | None:
        row = self._connection.execute(
            self._select()
            + """
            WHERE benchmark_id = %s
              AND universe_version_id = %s
              AND effective_session = %s
            """,
            (benchmark_id, universe_version_id, effective_session),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def list_forecasts(self) -> tuple[TimingForecast, ...]:
        rows = self._connection.execute(
            self._select() + " ORDER BY effective_session, benchmark_id, forecast_id"
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _columns() -> str:
        return """
            forecast_id, benchmark_id, universe_version_id, effective_session,
            decision_time, data_cutoff_at, created_at, data_mode, deployment_stage,
            horizon_forecasts, risk_forecast, static_exposure_ratio,
            passive_exposure_ratio, passive_target_volatility_ratio,
            passive_observed_volatility_ratio, passive_lookback_sessions,
            active_adjustment, final_exposure_lower_ratio, final_exposure_upper_ratio,
            model_version_id, model_lifecycle, run_id, approval_scope,
            dataset_version_ids, input_trust_state
        """

    @classmethod
    def _select(cls) -> str:
        return "SELECT " + cls._columns() + " FROM research.timing_forecasts"

    @staticmethod
    def to_row(value: TimingForecast) -> tuple[object, ...]:
        return (
            value.forecast_id,
            value.benchmark_id,
            value.universe_version_id,
            value.effective_session,
            value.decision_time,
            value.data_cutoff_at,
            value.created_at,
            value.context.data_mode.value,
            value.context.deployment_stage.value,
            [_horizon_document(item) for item in value.horizon_forecasts],
            _risk_document(value.risk_forecast),
            str(value.static_exposure_ratio),
            str(value.passive_exposure_ratio),
            str(value.passive_target_volatility_ratio),
            str(value.passive_observed_volatility_ratio),
            value.passive_lookback_sessions,
            _active_document(value.active_adjustment),
            str(value.final_exposure_lower_ratio),
            str(value.final_exposure_upper_ratio),
            value.model_version_id,
            value.model_lifecycle.value,
            value.run_id,
            value.approval_scope,
            list(value.dataset_version_ids),
            value.input_trust_state.value,
        )

    @classmethod
    def _from_row(cls, row: Sequence[object]) -> TimingForecast:
        raw_horizons = _json_value(row[9])
        if not isinstance(raw_horizons, list):
            raise TypeError("stored horizon_forecasts must be an array")
        horizons = tuple(cls._horizon_from_document(item) for item in raw_horizons)
        raw_risk = _json_value(row[10])
        raw_active = _json_value(row[16])
        raw_datasets = _json_value(row[23])
        if not isinstance(raw_risk, Mapping):
            raise TypeError("stored risk_forecast must be an object")
        if not isinstance(raw_active, Mapping):
            raise TypeError("stored active_adjustment must be an object")
        if not isinstance(raw_datasets, (list, tuple)):
            raise TypeError("stored dataset_version_ids must be an array")
        return TimingForecast(
            forecast_id=str(row[0]),
            benchmark_id=str(row[1]),
            universe_version_id=str(row[2]),
            effective_session=cast(date, row[3]),
            decision_time=cast(datetime, row[4]),
            data_cutoff_at=cast(datetime, row[5]),
            created_at=cast(datetime, row[6]),
            context=RunContext(DataMode(str(row[7])), DeploymentStage(str(row[8]))),
            horizon_forecasts=horizons,
            risk_forecast=cls._risk_from_document(raw_risk),
            static_exposure_ratio=_decimal(row[11], "static_exposure_ratio"),
            passive_exposure_ratio=_decimal(row[12], "passive_exposure_ratio"),
            passive_target_volatility_ratio=_decimal(
                row[13], "passive_target_volatility_ratio"
            ),
            passive_observed_volatility_ratio=_decimal(
                row[14], "passive_observed_volatility_ratio"
            ),
            passive_lookback_sessions=int(cast(int, row[15])),
            active_adjustment=cls._active_from_document(raw_active),
            final_exposure_lower_ratio=_decimal(row[17], "final_exposure_lower_ratio"),
            final_exposure_upper_ratio=_decimal(row[18], "final_exposure_upper_ratio"),
            model_version_id=str(row[19]),
            model_lifecycle=TimingModelLifecycle(str(row[20])),
            run_id=str(row[21]),
            approval_scope=str(row[22]),
            dataset_version_ids=tuple(str(item) for item in raw_datasets),
            input_trust_state=DataTrustState(str(row[24])),
        )

    @staticmethod
    def _optional_document_decimal(
        document: Mapping[object, object],
        field_name: str,
    ) -> Decimal | None:
        value = document.get(field_name)
        return None if value is None else _decimal(value, field_name)

    @classmethod
    def _horizon_from_document(cls, raw: object) -> HorizonReturnForecast:
        if not isinstance(raw, Mapping):
            raise TypeError("stored horizon forecast must be an object")
        return HorizonReturnForecast(
            horizon_trading_days=int(cast(int, raw.get("horizon_trading_days"))),
            status=TimingEstimateStatus(str(raw.get("status"))),
            up_probability=cls._optional_document_decimal(raw, "up_probability"),
            expected_return_ratio=cls._optional_document_decimal(
                raw, "expected_return_ratio"
            ),
            p10_return_ratio=cls._optional_document_decimal(raw, "p10_return_ratio"),
            p50_return_ratio=cls._optional_document_decimal(raw, "p50_return_ratio"),
            p90_return_ratio=cls._optional_document_decimal(raw, "p90_return_ratio"),
            status_reason=(
                None if raw.get("status_reason") is None else str(raw["status_reason"])
            ),
        )

    @classmethod
    def _risk_from_document(cls, raw: Mapping[object, object]) -> TimingRiskForecast:
        return TimingRiskForecast(
            status=TimingEstimateStatus(str(raw.get("status"))),
            annualized_volatility_ratio=cls._optional_document_decimal(
                raw, "annualized_volatility_ratio"
            ),
            maximum_drawdown_ratio=cls._optional_document_decimal(
                raw, "maximum_drawdown_ratio"
            ),
            tail_loss_ratio=cls._optional_document_decimal(raw, "tail_loss_ratio"),
            status_reason=(
                None if raw.get("status_reason") is None else str(raw["status_reason"])
            ),
        )

    @classmethod
    def _active_from_document(
        cls,
        raw: Mapping[object, object],
    ) -> ActiveTimingAdjustment:
        return ActiveTimingAdjustment(
            status=TimingEstimateStatus(str(raw.get("status"))),
            point_exposure_delta=cls._optional_document_decimal(
                raw, "point_exposure_delta"
            ),
            lower_exposure_delta=cls._optional_document_decimal(
                raw, "lower_exposure_delta"
            ),
            upper_exposure_delta=cls._optional_document_decimal(
                raw, "upper_exposure_delta"
            ),
            status_reason=(
                None if raw.get("status_reason") is None else str(raw["status_reason"])
            ),
        )
