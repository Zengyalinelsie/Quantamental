"""Point-in-time financial facts and data-trust contracts.

Market decision time and warehouse knowledge time are independent.  A public
revision changes what was available to the market; a system correction changes
what a particular warehouse snapshot knew without rewriting earlier snapshots.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from math import isfinite
from typing import TypeAlias

from .metrics import MetricUnit, StatementType
from .run_context import DataMode

FactValue: TypeAlias = str | int | float | bool
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_CURRENCY_UNITS = {MetricUnit.CURRENCY, MetricUnit.CURRENCY_PER_SHARE}


class DataTrustState(str, Enum):
    RAW = "raw"
    NORMALIZED_CURRENT = "normalized_current"
    PIT_VERIFIED = "pit_verified"


class DataQualityState(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"

    @property
    def blocks_downstream(self) -> bool:
        return self in {self.BLOCKED, self.UNAVAILABLE}


class FinancialPeriodType(str, Enum):
    Q1 = "q1"
    HALF_YEAR = "half_year"
    Q3 = "q3"
    ANNUAL = "annual"
    TTM = "ttm"


class PointInTimeConflictError(RuntimeError):
    """Raised when one PIT query has more than one authoritative visible result."""


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class AuthorityRule:
    """An immutable, caller-selected provider precedence version."""

    rule_version: str
    provider_priority: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text(self.rule_version, "rule_version")
        providers = tuple(self.provider_priority)
        if not providers:
            raise ValueError("provider_priority must not be empty")
        for provider in providers:
            _require_text(provider, "provider_priority item")
        if len(providers) != len(set(providers)):
            raise ValueError("provider_priority must contain unique providers")
        object.__setattr__(self, "provider_priority", providers)


@dataclass(frozen=True)
class FactObservation:
    """One source observation with economic, public, and system-time dimensions."""

    fact_id: str
    company_id: str
    security_id: str
    metric_code: str
    value: FactValue
    unit: MetricUnit
    currency: str | None
    report_period_end: date
    period_type: FinancialPeriodType
    statement_type: StatementType
    announced_at: datetime
    available_at: datetime
    known_from: datetime
    known_to: datetime | None
    revision_sequence: int
    provider_id: str
    source_field: str
    raw_object_hash: str
    trust_state: DataTrustState
    quality_state: DataQualityState
    mapping_version_id: str
    source_object_id: str
    dataset_version_id: str
    quality_issue_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "fact_id",
            "company_id",
            "security_id",
            "metric_code",
            "provider_id",
            "source_field",
            "mapping_version_id",
            "source_object_id",
            "dataset_version_id",
        ):
            _require_text(getattr(self, name), name)
        if type(self.value) not in {str, int, float, bool}:
            raise TypeError("value must be a string, integer, float, or boolean")
        if isinstance(self.value, float) and not isfinite(self.value):
            raise ValueError("numeric fact value must be finite")

        unit = MetricUnit(self.unit)
        object.__setattr__(self, "unit", unit)
        if unit in _CURRENCY_UNITS:
            if self.currency is None:
                raise ValueError("currency is required for currency-valued facts")
            if not re.fullmatch(r"[A-Z]{3}", self.currency):
                raise ValueError("currency must be a three-letter uppercase ISO code")
        elif self.currency is not None:
            raise ValueError("currency must be absent for non-currency facts")

        if not isinstance(self.report_period_end, date) or isinstance(
            self.report_period_end, datetime
        ):
            raise TypeError("report_period_end must be a date")
        object.__setattr__(self, "period_type", FinancialPeriodType(self.period_type))
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))

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
        if not isinstance(self.raw_object_hash, str) or _SHA256.fullmatch(
            self.raw_object_hash
        ) is None:
            raise ValueError("raw_object_hash must use sha256:<64 lowercase hex chars>")

        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        quality_state = DataQualityState(self.quality_state)
        object.__setattr__(self, "quality_state", quality_state)
        issues = tuple(self.quality_issue_ids)
        if any(not isinstance(issue, str) or not issue.strip() for issue in issues):
            raise ValueError("quality_issue_ids must contain non-empty identifiers")
        if len(issues) != len(set(issues)):
            raise ValueError("quality_issue_ids must be unique")
        if quality_state.blocks_downstream and not issues:
            raise ValueError("quality_issue_ids are required for blocked or unavailable facts")
        object.__setattr__(self, "quality_issue_ids", issues)

    @property
    def economic_identity(self) -> tuple[object, ...]:
        return (
            self.company_id,
            self.security_id,
            self.metric_code,
            self.report_period_end,
            self.period_type,
            self.statement_type,
        )

    @property
    def source_revision_identity(self) -> tuple[object, ...]:
        return (*self.economic_identity, self.provider_id, self.revision_sequence)

    @property
    def semantic_value(self) -> tuple[object, ...]:
        return (self.value, self.unit, self.currency)

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
        """Return whether this exact version may serve the requested data mode."""

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


@dataclass(frozen=True)
class FactSelection:
    selected: FactObservation | None
    conflicting_fact_ids: tuple[str, ...]
    quality_issue_ids: tuple[str, ...]
    authority_rule_version: str
    blocks_downstream: bool


def select_fact_as_of(
    observations: Iterable[FactObservation],
    data_mode: DataMode,
    *,
    decision_time: datetime,
    system_time: datetime,
) -> FactObservation | None:
    """Select the highest public revision eligible at both requested clocks."""

    rows = tuple(observations)
    if not rows:
        return None
    identities = {row.economic_identity for row in rows}
    if len(identities) != 1:
        raise ValueError("observations must describe one economic fact identity")
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
