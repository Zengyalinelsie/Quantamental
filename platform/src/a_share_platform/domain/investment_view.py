"""Unified, version-bound investment judgment consumed by portfolio services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from math import isfinite


def _finite(value: float, field_name: str) -> float:
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    return number


@dataclass(frozen=True)
class ExpectedReturnDistribution:
    point: float
    p10: float
    p50: float
    p90: float

    def __post_init__(self) -> None:
        for name in ("point", "p10", "p50", "p90"):
            object.__setattr__(self, name, _finite(getattr(self, name), name))
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("expected-return percentiles must satisfy p10 <= p50 <= p90")
        if not self.p10 <= self.point <= self.p90:
            raise ValueError("point estimate must lie inside [p10, p90]")


class InvestmentComponentStatus(str, Enum):
    QUANTIFIED = "quantified"
    CONSTRAINED = "constrained"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class InvestmentComponent:
    name: str
    status: InvestmentComponentStatus
    expected_return_contribution: float | None = None
    evidence_ids: tuple[str, ...] = ()
    status_reason: str | None = None

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise ValueError("component name must not be empty")
        status = InvestmentComponentStatus(self.status)
        object.__setattr__(self, "status", status)
        if any(not str(value or "").strip() for value in self.evidence_ids):
            raise ValueError("component evidence ids must not be empty")
        if status is InvestmentComponentStatus.QUANTIFIED:
            if self.expected_return_contribution is None:
                raise ValueError("quantified component requires an expected-return contribution")
            object.__setattr__(
                self,
                "expected_return_contribution",
                _finite(self.expected_return_contribution, "expected_return_contribution"),
            )
            if not self.evidence_ids:
                raise ValueError("quantified component requires at least one evidence id")
        else:
            if self.expected_return_contribution is not None:
                raise ValueError(
                    f"{status.value} component must not have a numeric contribution"
                )
            if not str(self.status_reason or "").strip():
                raise ValueError(f"{status.value} component requires an explicit reason")


@dataclass(frozen=True)
class InvestmentView:
    view_id: str
    security_id: str
    decision_time: datetime
    horizon_trading_days: int
    expected_return: ExpectedReturnDistribution
    confidence: float
    components: tuple[InvestmentComponent, ...]
    residual: float
    invalidators: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    model_version_id: str

    def __post_init__(self) -> None:
        for name in ("view_id", "security_id", "model_version_id"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must not be empty")
        if self.decision_time.tzinfo is None or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be timezone-aware")
        if type(self.horizon_trading_days) is not int or self.horizon_trading_days <= 0:
            raise ValueError("horizon_trading_days must be a positive integer")
        confidence = _finite(self.confidence, "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        object.__setattr__(self, "confidence", confidence)
        if not self.components:
            raise ValueError("InvestmentView requires at least one component")
        component_names = [item.name for item in self.components]
        if len(component_names) != len(set(component_names)):
            raise ValueError("component names must be unique")
        object.__setattr__(self, "residual", _finite(self.residual, "residual"))
        if not self.invalidators or any(not str(value or "").strip() for value in self.invalidators):
            raise ValueError("InvestmentView requires explicit invalidators")
        if not self.dataset_version_ids or any(
            not str(value or "").strip() for value in self.dataset_version_ids
        ):
            raise ValueError("InvestmentView requires dataset version bindings")
        if abs(self.reconciled_expected_return - self.expected_return.point) > 1e-9:
            raise ValueError(
                "quantified component contributions plus residual must reconcile "
                "to the point expected return"
            )

    @property
    def component_total(self) -> float:
        return sum(
            item.expected_return_contribution
            for item in self.components
            if item.status is InvestmentComponentStatus.QUANTIFIED
            and item.expected_return_contribution is not None
        )

    @property
    def reconciled_expected_return(self) -> float:
        return self.component_total + self.residual

    @property
    def all_evidence_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                evidence_id
                for component in self.components
                for evidence_id in component.evidence_ids
            )
        )
