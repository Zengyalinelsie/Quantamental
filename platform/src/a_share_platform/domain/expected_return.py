"""Expected Return Compiler V0 and immutable outcome/calibration records.

The compiler is deterministic and provider-neutral.  It assembles already
qualified component evidence; it does not invent missing estimates or promote
current data to point-in-time data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import IntEnum

from .investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from .pit import DataTrustState
from .run_context import DataMode, RunContext

_CORE_COMPONENTS = ("quality", "valuation", "revision", "event")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result or any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty text")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be unique")
    return result


class InvestmentHorizon(IntEnum):
    DAYS_20 = 20
    DAYS_60 = 60
    DAYS_120 = 120


class ExpectedReturnUnavailable(RuntimeError):
    """Raised when the compiler has no quantified signal to assemble."""


@dataclass(frozen=True)
class ExpectedReturnResidual:
    value: Decimal
    reason: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _decimal(self.value, "residual value")
        _text(self.reason, "residual reason")
        object.__setattr__(
            self,
            "evidence_ids",
            _unique_texts(self.evidence_ids, "residual evidence_ids"),
        )


@dataclass(frozen=True)
class ExpectedReturnCompileRequest:
    security_id: str
    decision_time: datetime
    horizon: InvestmentHorizon
    components: tuple[InvestmentComponent, ...]
    residual: ExpectedReturnResidual
    p10: Decimal
    p50: Decimal
    p90: Decimal
    downside: Decimal
    confidence: Decimal
    catalysts: tuple[str, ...]
    invalidators: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    feature_version_ids: tuple[str, ...]
    model_version_id: str
    run_id: str
    code_version: str
    environment_id: str
    run_context: RunContext
    trust_state: DataTrustState
    latest_input_available_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "security_id",
            "model_version_id",
            "run_id",
            "code_version",
            "environment_id",
        ):
            _text(getattr(self, name), name)
        decision_time = _aware(self.decision_time, "decision_time")
        latest_available = _aware(
            self.latest_input_available_at,
            "latest_input_available_at",
        )
        if latest_available > decision_time:
            raise ValueError("latest_input_available_at cannot exceed decision_time")
        try:
            horizon = InvestmentHorizon(self.horizon)
        except (TypeError, ValueError) as error:
            raise ValueError("horizon must be 20, 60, or 120 trading days") from error
        object.__setattr__(self, "horizon", horizon)
        components = tuple(self.components)
        if any(not isinstance(item, InvestmentComponent) for item in components):
            raise TypeError("components must contain InvestmentComponent values")
        by_name = {item.name: item for item in components}
        if len(by_name) != len(components) or set(by_name) != set(_CORE_COMPONENTS):
            raise ValueError("components must contain exactly quality, valuation, revision, event")
        object.__setattr__(self, "components", tuple(by_name[name] for name in _CORE_COMPONENTS))
        if not isinstance(self.residual, ExpectedReturnResidual):
            raise TypeError("residual must be an ExpectedReturnResidual")
        for name in ("p10", "p50", "p90", "downside", "confidence"):
            _decimal(getattr(self, name), name)
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise ValueError("confidence must be in [0, 1]")
        for name in (
            "catalysts",
            "invalidators",
            "dataset_version_ids",
            "feature_version_ids",
        ):
            object.__setattr__(self, name, _unique_texts(getattr(self, name), name))
        if not isinstance(self.run_context, RunContext):
            raise TypeError("run_context must be a RunContext")
        trust_state = DataTrustState(self.trust_state)
        if trust_state is DataTrustState.RAW:
            raise ValueError("raw inputs cannot enter the Expected Return Compiler")
        if (
            self.run_context.data_mode is DataMode.STRICT_HISTORICAL
            and trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise ValueError("strict_historical requires pit_verified inputs")
        object.__setattr__(self, "trust_state", trust_state)

    def hash_payload(self) -> dict[str, object]:
        return {
            "security_id": self.security_id,
            "decision_time": _canonical_time(self.decision_time),
            "horizon": int(self.horizon),
            "components": tuple(item.hash_payload() for item in self.components),
            "residual": {
                "value": _decimal_text(self.residual.value),
                "reason": self.residual.reason,
                "evidence_ids": self.residual.evidence_ids,
            },
            "p10": _decimal_text(self.p10),
            "p50": _decimal_text(self.p50),
            "p90": _decimal_text(self.p90),
            "downside": _decimal_text(self.downside),
            "confidence": _decimal_text(self.confidence),
            "catalysts": self.catalysts,
            "invalidators": self.invalidators,
            "dataset_version_ids": self.dataset_version_ids,
            "feature_version_ids": self.feature_version_ids,
            "model_version_id": self.model_version_id,
            "run_id": self.run_id,
            "code_version": self.code_version,
            "environment_id": self.environment_id,
            "run_context": {
                "data_mode": self.run_context.data_mode.value,
                "deployment_stage": self.run_context.deployment_stage.value,
            },
            "trust_state": self.trust_state.value,
            "latest_input_available_at": _canonical_time(self.latest_input_available_at),
        }


class ExpectedReturnCompilerV0:
    """Compile an auditable V0 view without manufacturing absent components."""

    def compile(self, request: ExpectedReturnCompileRequest) -> InvestmentView:
        if not isinstance(request, ExpectedReturnCompileRequest):
            raise TypeError("request must be an ExpectedReturnCompileRequest")
        event = next(item for item in request.components if item.name == "event")
        if event.status is not InvestmentComponentStatus.UNAVAILABLE:
            raise ValueError("event must remain unavailable before P8")
        if not any(
            item.status is InvestmentComponentStatus.QUANTIFIED
            for item in request.components
        ):
            raise ExpectedReturnUnavailable(
                "no quantified component is available; residual cannot manufacture a signal"
            )
        point = sum(
            (
                item.expected_return_contribution
                for item in request.components
                if item.status is InvestmentComponentStatus.QUANTIFIED
                and item.expected_return_contribution is not None
            ),
            Decimal(0),
        ) + request.residual.value
        request_hash = _canonical_hash(request.hash_payload())
        return InvestmentView(
            view_id=f"investment-view:{request_hash}",
            security_id=request.security_id,
            decision_time=request.decision_time,
            horizon_trading_days=int(request.horizon),
            expected_return=ExpectedReturnDistribution(
                point=point,
                p10=request.p10,
                p50=request.p50,
                p90=request.p90,
                downside=request.downside,
            ),
            confidence=request.confidence,
            components=request.components,
            residual=request.residual.value,
            residual_reason=request.residual.reason,
            residual_evidence_ids=request.residual.evidence_ids,
            catalysts=request.catalysts,
            invalidators=request.invalidators,
            dataset_version_ids=request.dataset_version_ids,
            feature_version_ids=request.feature_version_ids,
            model_version_id=request.model_version_id,
            run_id=request.run_id,
            code_version=request.code_version,
            environment_id=request.environment_id,
            run_context=request.run_context,
            trust_state=request.trust_state,
            latest_input_available_at=request.latest_input_available_at,
        )


@dataclass(frozen=True)
class InvestmentViewOutcome:
    outcome_id: str
    view_id: str
    security_id: str
    decision_time: datetime
    horizon_trading_days: int
    realized_at: datetime
    realized_return: Decimal
    dataset_version_id: str
    recorded_at: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("outcome_id", "view_id", "security_id", "dataset_version_id"):
            _text(getattr(self, name), name)
        decision_time = _aware(self.decision_time, "decision_time")
        realized_at = _aware(self.realized_at, "realized_at")
        recorded_at = _aware(self.recorded_at, "recorded_at")
        if type(self.horizon_trading_days) is not int or self.horizon_trading_days not in {
            20,
            60,
            120,
        }:
            raise ValueError("horizon_trading_days must be 20, 60, or 120")
        if realized_at <= decision_time:
            raise ValueError("realized_at must be later than decision_time")
        if recorded_at < realized_at:
            raise ValueError("recorded_at cannot precede realized_at")
        _decimal(self.realized_return, "realized_return")
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    def hash_payload(self) -> dict[str, object]:
        return {
            "outcome_id": self.outcome_id,
            "view_id": self.view_id,
            "security_id": self.security_id,
            "decision_time": _canonical_time(self.decision_time),
            "horizon_trading_days": self.horizon_trading_days,
            "realized_at": _canonical_time(self.realized_at),
            "realized_return": _decimal_text(self.realized_return),
            "dataset_version_id": self.dataset_version_id,
            "recorded_at": _canonical_time(self.recorded_at),
        }


@dataclass(frozen=True)
class ExpectedReturnCalibrationRecord:
    calibration_id: str
    view_id: str
    outcome_id: str
    predicted_return: Decimal
    realized_return: Decimal
    absolute_error: Decimal
    inside_p10_p90: bool
    direction_correct: bool
    recorded_at: datetime
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("calibration_id", "view_id", "outcome_id"):
            _text(getattr(self, name), name)
        for name in ("predicted_return", "realized_return", "absolute_error"):
            _decimal(getattr(self, name), name)
        if self.absolute_error < Decimal(0):
            raise ValueError("absolute_error cannot be negative")
        _aware(self.recorded_at, "recorded_at")
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    @classmethod
    def from_view_and_outcome(
        cls,
        *,
        calibration_id: str,
        view: InvestmentView,
        outcome: InvestmentViewOutcome,
        recorded_at: datetime,
    ) -> ExpectedReturnCalibrationRecord:
        if not isinstance(view, InvestmentView):
            raise TypeError("view must be an InvestmentView")
        if not isinstance(outcome, InvestmentViewOutcome):
            raise TypeError("outcome must be an InvestmentViewOutcome")
        if (
            outcome.view_id != view.view_id
            or outcome.security_id != view.security_id
            or outcome.decision_time != view.decision_time
            or outcome.horizon_trading_days != view.horizon_trading_days
        ):
            raise ValueError("outcome identity does not match InvestmentView")
        recorded_at = _aware(recorded_at, "recorded_at")
        if recorded_at < outcome.recorded_at:
            raise ValueError("calibration recorded_at cannot precede outcome recorded_at")
        predicted = view.expected_return.point
        realized = outcome.realized_return
        return cls(
            calibration_id=calibration_id,
            view_id=view.view_id,
            outcome_id=outcome.outcome_id,
            predicted_return=predicted,
            realized_return=realized,
            absolute_error=abs(predicted - realized),
            inside_p10_p90=view.expected_return.p10 <= realized <= view.expected_return.p90,
            direction_correct=(
                (predicted > 0 and realized > 0)
                or (predicted < 0 and realized < 0)
                or (predicted == 0 and realized == 0)
            ),
            recorded_at=recorded_at,
        )

    def hash_payload(self) -> dict[str, object]:
        return {
            "calibration_id": self.calibration_id,
            "view_id": self.view_id,
            "outcome_id": self.outcome_id,
            "predicted_return": _decimal_text(self.predicted_return),
            "realized_return": _decimal_text(self.realized_return),
            "absolute_error": _decimal_text(self.absolute_error),
            "inside_p10_p90": self.inside_p10_p90,
            "direction_correct": self.direction_correct,
            "recorded_at": _canonical_time(self.recorded_at),
        }
