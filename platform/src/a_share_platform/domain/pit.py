"""Point-in-time and data-trust contracts.

The domain distinguishes market decision time from warehouse knowledge time.
That distinction is required to replay public information without pretending a
later backfill was already present in the warehouse.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import Iterable, TypeAlias

from .run_context import DataMode

FactValue: TypeAlias = str | int | float | bool


class DataTrustState(str, Enum):
    RAW = "raw"
    NORMALIZED_CURRENT = "normalized_current"
    PIT_VERIFIED = "pit_verified"


class PointInTimeConflictError(RuntimeError):
    """Raised when one PIT query has more than one authoritative visible result."""


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class FactObservation:
    """One versioned fact with economic, public-availability, and system time."""

    fact_id: str
    security_id: str
    metric_code: str
    value: FactValue
    report_period_end: date
    announced_at: datetime
    available_at: datetime
    known_from: datetime
    known_to: datetime | None
    revision_sequence: int
    trust_state: DataTrustState
    source_object_id: str

    def __post_init__(self) -> None:
        for name in ("fact_id", "security_id", "metric_code", "source_object_id"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"{name} must not be empty")
        if not isinstance(self.report_period_end, date):
            raise ValueError("report_period_end must be a date")
        announced_at = _require_aware(self.announced_at, "announced_at")
        available_at = _require_aware(self.available_at, "available_at")
        known_from = _require_aware(self.known_from, "known_from")
        known_to = None if self.known_to is None else _require_aware(self.known_to, "known_to")
        if available_at < announced_at:
            raise ValueError("available_at cannot precede announced_at")
        if known_to is not None and known_to <= known_from:
            raise ValueError("known_to must be later than known_from")
        if type(self.revision_sequence) is not int or self.revision_sequence < 0:
            raise ValueError("revision_sequence must be a non-negative integer")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("numeric fact value must be finite")
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))

    def visible_in_system(self, system_time: datetime) -> bool:
        system_time = _require_aware(system_time, "system_time")
        return self.known_from <= system_time and (
            self.known_to is None or system_time < self.known_to
        )

    def eligible_for(
        self,
        data_mode: DataMode,
        *,
        decision_time: datetime,
        system_time: datetime,
    ) -> bool:
        """Return whether this exact fact version may serve the requested use case."""

        data_mode = DataMode(data_mode)
        decision_time = _require_aware(decision_time, "decision_time")
        if not self.visible_in_system(system_time):
            return False
        if self.available_at > decision_time:
            return False
        if data_mode is DataMode.STRICT_HISTORICAL:
            return self.trust_state is DataTrustState.PIT_VERIFIED
        return self.trust_state in {
            DataTrustState.NORMALIZED_CURRENT,
            DataTrustState.PIT_VERIFIED,
        }


def select_fact_as_of(
    observations: Iterable[FactObservation],
    data_mode: DataMode,
    *,
    decision_time: datetime,
    system_time: datetime,
) -> FactObservation | None:
    """Select the highest public revision eligible at both requested clocks.

    All candidates must describe one security, metric, and economic period. A
    duplicate visible version is a data conflict and fails closed.
    """

    rows = tuple(observations)
    if not rows:
        return None
    identities = {
        (row.security_id, row.metric_code, row.report_period_end)
        for row in rows
    }
    if len(identities) != 1:
        raise ValueError("observations must describe one security, metric, and report period")
    eligible = tuple(
        row
        for row in rows
        if row.eligible_for(
            data_mode,
            decision_time=decision_time,
            system_time=system_time,
        )
    )
    if not eligible:
        return None
    highest_revision = max(row.revision_sequence for row in eligible)
    winners = tuple(row for row in eligible if row.revision_sequence == highest_revision)
    if len(winners) != 1:
        raise PointInTimeConflictError(
            "multiple visible facts share the highest eligible revision"
        )
    return winners[0]
