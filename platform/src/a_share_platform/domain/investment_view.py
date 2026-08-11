"""Frozen, version-bound investment judgments consumed by portfolio services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum

from .pit import DataTrustState
from .run_context import DataMode, RunContext


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


def _unique_texts(
    values: tuple[str, ...],
    field_name: str,
    *,
    required: bool = True,
) -> tuple[str, ...]:
    result = tuple(values)
    if required and not result:
        raise ValueError(f"{field_name} must not be empty")
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty text")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be unique")
    return result


@dataclass(frozen=True)
class ExpectedReturnDistribution:
    point: Decimal
    p10: Decimal
    p50: Decimal
    p90: Decimal
    downside: Decimal

    def __post_init__(self) -> None:
        for name in ("point", "p10", "p50", "p90", "downside"):
            _decimal(getattr(self, name), name)
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("expected-return percentiles must satisfy p10 <= p50 <= p90")
        if not self.p10 <= self.point <= self.p90:
            raise ValueError("point estimate must lie inside [p10, p90]")
        if self.downside > self.point:
            raise ValueError("downside must not exceed the point expected return")


class InvestmentComponentStatus(str, Enum):
    QUANTIFIED = "quantified"
    CONSTRAINED = "constrained"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class InvestmentComponent:
    name: str
    status: InvestmentComponentStatus
    expected_return_contribution: Decimal | None = None
    evidence_ids: tuple[str, ...] = ()
    status_reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.name, "component name")
        status = InvestmentComponentStatus(self.status)
        object.__setattr__(self, "status", status)
        evidence_ids = _unique_texts(self.evidence_ids, "component evidence ids", required=False)
        object.__setattr__(self, "evidence_ids", evidence_ids)
        if status is InvestmentComponentStatus.QUANTIFIED:
            if self.expected_return_contribution is None:
                raise ValueError("quantified component requires an expected-return contribution")
            _decimal(self.expected_return_contribution, "expected_return_contribution")
            if not evidence_ids:
                raise ValueError("quantified component requires at least one evidence id")
        else:
            if self.expected_return_contribution is not None:
                raise ValueError(
                    f"{status.value} component must not have a numeric contribution"
                )
            if not isinstance(self.status_reason, str) or not self.status_reason.strip():
                raise ValueError(f"{status.value} component requires an explicit reason")

    def hash_payload(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "expected_return_contribution": (
                None
                if self.expected_return_contribution is None
                else _decimal_text(self.expected_return_contribution)
            ),
            "evidence_ids": self.evidence_ids,
            "status_reason": self.status_reason,
        }


@dataclass(frozen=True)
class InvestmentView:
    view_id: str
    security_id: str
    decision_time: datetime
    horizon_trading_days: int
    expected_return: ExpectedReturnDistribution
    confidence: Decimal
    components: tuple[InvestmentComponent, ...]
    residual: Decimal
    residual_reason: str
    residual_evidence_ids: tuple[str, ...]
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
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "view_id",
            "security_id",
            "model_version_id",
            "run_id",
            "code_version",
            "environment_id",
            "residual_reason",
        ):
            _text(getattr(self, name), name)
        decision_time = _aware(self.decision_time, "decision_time")
        latest_available = _aware(
            self.latest_input_available_at,
            "latest_input_available_at",
        )
        if latest_available > decision_time:
            raise ValueError("latest_input_available_at cannot exceed decision_time")
        if type(self.horizon_trading_days) is not int or self.horizon_trading_days not in {
            20,
            60,
            120,
        }:
            raise ValueError("horizon_trading_days must be 20, 60, or 120")
        if not isinstance(self.expected_return, ExpectedReturnDistribution):
            raise TypeError("expected_return must be an ExpectedReturnDistribution")
        confidence = _decimal(self.confidence, "confidence")
        if not Decimal(0) <= confidence <= Decimal(1):
            raise ValueError("confidence must be in [0, 1]")
        components = tuple(self.components)
        if not components:
            raise ValueError("InvestmentView requires at least one component")
        if any(not isinstance(item, InvestmentComponent) for item in components):
            raise TypeError("components must contain InvestmentComponent values")
        component_names = [item.name for item in components]
        if len(component_names) != len(set(component_names)):
            raise ValueError("component names must be unique")
        object.__setattr__(self, "components", components)
        _decimal(self.residual, "residual")
        object.__setattr__(
            self,
            "residual_evidence_ids",
            _unique_texts(self.residual_evidence_ids, "residual_evidence_ids"),
        )
        if not self.invalidators:
            raise ValueError("InvestmentView requires explicit invalidators")
        for field_name in ("catalysts", "invalidators", "dataset_version_ids"):
            object.__setattr__(
                self,
                field_name,
                _unique_texts(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "feature_version_ids",
            _unique_texts(self.feature_version_ids, "feature_version_ids"),
        )
        if not isinstance(self.run_context, RunContext):
            raise TypeError("run_context must be a RunContext")
        trust_state = DataTrustState(self.trust_state)
        if trust_state is DataTrustState.RAW:
            raise ValueError("raw inputs cannot produce an InvestmentView")
        if (
            self.run_context.data_mode is DataMode.STRICT_HISTORICAL
            and trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise ValueError("strict_historical requires pit_verified inputs")
        object.__setattr__(self, "trust_state", trust_state)
        if self.reconciled_expected_return != self.expected_return.point:
            raise ValueError(
                "quantified component contributions plus residual must reconcile "
                "to the point expected return"
            )
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    @property
    def component_total(self) -> Decimal:
        return sum(
            (
                item.expected_return_contribution
                for item in self.components
                if item.status is InvestmentComponentStatus.QUANTIFIED
                and item.expected_return_contribution is not None
            ),
            Decimal(0),
        )

    @property
    def reconciled_expected_return(self) -> Decimal:
        return self.component_total + self.residual

    @property
    def all_evidence_ids(self) -> tuple[str, ...]:
        component_evidence = tuple(
            evidence_id
            for component in self.components
            for evidence_id in component.evidence_ids
        )
        return tuple(
            dict.fromkeys((*component_evidence, *self.residual_evidence_ids))
        )

    def hash_payload(self) -> dict[str, object]:
        return {
            "view_id": self.view_id,
            "security_id": self.security_id,
            "decision_time": _canonical_time(self.decision_time),
            "horizon_trading_days": self.horizon_trading_days,
            "expected_return": {
                "point": _decimal_text(self.expected_return.point),
                "p10": _decimal_text(self.expected_return.p10),
                "p50": _decimal_text(self.expected_return.p50),
                "p90": _decimal_text(self.expected_return.p90),
                "downside": _decimal_text(self.expected_return.downside),
            },
            "confidence": _decimal_text(self.confidence),
            "components": tuple(item.hash_payload() for item in self.components),
            "residual": _decimal_text(self.residual),
            "residual_reason": self.residual_reason,
            "residual_evidence_ids": self.residual_evidence_ids,
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
