"""Forward-return labels: the dependent variable of every factor study.

A label answers "what happened next", so a silently wrong one invalidates every
statistic computed from it.  This module therefore fails closed on every case
where the honest answer is "unknown": a missing or suspended entry session, a
suspended exit session, a horizon that runs past the available history, or a
non-positive entry price.  None of those becomes a zero, because a zero label
reads as "the price did not move" rather than "we do not know".

Horizons count **trading sessions**, not calendar days, so a holiday or a
suspension never silently shortens the measurement window.

Scope: this module is part of the current-only research track
(`docs/plans/step-03a-current-only-factor-research.md`).  It refuses
`strict_historical`, because a strict label requires `pit_verified` prices whose
availability at the decision time has been verified — which the current data
cannot support.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum, StrEnum

from .market_data import PriceAdjustment
from .pit import DataTrustState
from .run_context import DataMode


class LabelHorizon(int, Enum):
    """Forward window length in trading sessions."""

    TWENTY_SESSIONS = 20
    SIXTY_SESSIONS = 60
    ONE_HUNDRED_TWENTY_SESSIONS = 120


class LabelObservationStatus(StrEnum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


class LabelUnavailableReason(StrEnum):
    DECISION_SESSION_MISSING = "decision_session_missing"
    HORIZON_INCOMPLETE = "horizon_incomplete"
    NOT_TRADABLE = "not_tradable"
    INVALID_PRICE = "invalid_price"


_UNADJUSTED_LIMITATION = (
    "未复权价格：缺少公司行动（分红、送转、配股）数据，跨除权日的收益可能失真。"
    "This label uses unadjusted prices; without corporate action data a return "
    "spanning an ex-rights date may be wrong."
)


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


@dataclass(frozen=True)
class LabelPriceInput:
    """One session's close, with whether the name could actually be traded."""

    session_date: date
    close: Decimal
    tradable: bool

    def __post_init__(self) -> None:
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        if not isinstance(self.close, Decimal):
            raise TypeError("close must be a Decimal")
        if not self.close.is_finite():
            raise ValueError("close must be finite")
        if self.close < 0:
            raise ValueError("close must not be negative")
        if not isinstance(self.tradable, bool):
            raise TypeError("tradable must be a bool")


@dataclass(frozen=True)
class ForwardReturnObservation:
    """One label value, or an explicit statement that there is none."""

    label_id: str
    label_version: str
    definition_hash: str
    horizon: LabelHorizon
    status: LabelObservationStatus
    value: Decimal | None = None
    reason: LabelUnavailableReason | None = None
    entry_session: date | None = None
    exit_session: date | None = None

    def __post_init__(self) -> None:
        if self.status is LabelObservationStatus.QUANTIFIED:
            if self.value is None:
                raise ValueError("a quantified label requires a value")
            if self.reason is not None:
                raise ValueError("a quantified label must not carry a reason")
        else:
            if self.value is not None:
                raise ValueError("an unavailable label must not carry a value")
            if self.reason is None:
                raise ValueError("an unavailable label must state a reason")


@dataclass(frozen=True)
class ForwardReturnLabelDefinition:
    """Versioned, content-addressed forward-return definition."""

    label_id: str
    version: str
    horizon: LabelHorizon
    adjustment: PriceAdjustment
    data_mode: DataMode
    trust_state: DataTrustState
    content_hash: str = ""

    def __post_init__(self) -> None:
        _text(self.label_id, "label_id")
        _text(self.version, "version")
        horizon = LabelHorizon(self.horizon)
        object.__setattr__(self, "horizon", horizon)
        object.__setattr__(self, "adjustment", PriceAdjustment(self.adjustment))
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError(
                "strict_historical forward-return labels require pit_verified prices"
            )
        if trust is DataTrustState.RAW:
            raise ValueError("raw prices cannot produce a label")
        payload = {
            "label_id": self.label_id,
            "version": self.version,
            "horizon": int(horizon),
            "adjustment": self.adjustment.value,
            "data_mode": mode.value,
            "trust_state": trust.value,
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        object.__setattr__(
            self, "content_hash", hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        )

    @property
    def limitation(self) -> str:
        """The caveat that must travel with every value this definition produces."""
        return _UNADJUSTED_LIMITATION

    def _unavailable(self, reason: LabelUnavailableReason) -> ForwardReturnObservation:
        return ForwardReturnObservation(
            label_id=self.label_id,
            label_version=self.version,
            definition_hash=self.content_hash,
            horizon=self.horizon,
            status=LabelObservationStatus.UNAVAILABLE,
            reason=reason,
        )

    def calculate(
        self,
        *,
        decision_session: date,
        prices: tuple[LabelPriceInput, ...],
    ) -> ForwardReturnObservation:
        ordered = sorted(prices, key=lambda item: item.session_date)
        sessions = [item.session_date for item in ordered]
        if len(sessions) != len(set(sessions)):
            raise ValueError("prices must not contain duplicate sessions")

        try:
            entry_index = sessions.index(decision_session)
        except ValueError:
            return self._unavailable(LabelUnavailableReason.DECISION_SESSION_MISSING)

        exit_index = entry_index + int(self.horizon)
        if exit_index >= len(ordered):
            # Truncating the window would silently change the horizon.
            return self._unavailable(LabelUnavailableReason.HORIZON_INCOMPLETE)

        entry = ordered[entry_index]
        exit_bar = ordered[exit_index]
        if not entry.tradable or not exit_bar.tradable:
            return self._unavailable(LabelUnavailableReason.NOT_TRADABLE)
        if entry.close <= 0:
            return self._unavailable(LabelUnavailableReason.INVALID_PRICE)

        value = (exit_bar.close - entry.close) / entry.close
        return ForwardReturnObservation(
            label_id=self.label_id,
            label_version=self.version,
            definition_hash=self.content_hash,
            horizon=self.horizon,
            status=LabelObservationStatus.QUANTIFIED,
            value=value,
            entry_session=entry.session_date,
            exit_session=exit_bar.session_date,
        )


__all__ = [
    "ForwardReturnLabelDefinition",
    "ForwardReturnObservation",
    "LabelHorizon",
    "LabelObservationStatus",
    "LabelPriceInput",
    "LabelUnavailableReason",
]
