"""Desk section contracts for the prototype Platform Pulse workstation.

The desk answers "what changed since I last looked, and can I trust it" across
seven independent domains.  Those domains mature at different phases, so the
contract makes each section carry its own status and its own reason instead of
collapsing the page into a single verdict: one blocked domain must never blank
the other six.

Four statuses are modelled here because the server can only speak to data
facts.  ``loading`` and ``error`` belong to the request lifecycle and are owned
by the client.  The distinction between :attr:`DeskSectionStatus.EMPTY` and
:attr:`DeskSectionStatus.UNAVAILABLE` is deliberate and load-bearing: empty
means the capability exists and holds no record yet, unavailable means the
capability itself is missing or its store cannot be reached.  Collapsing them
would hide whether the operator is waiting on data or on implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DeskSectionKey(StrEnum):
    """The seven prototype sections, ordered as they appear in the 1440 design."""

    DATA_HEALTH = "data_health"
    SCREEN_SHIFTS = "screen_shifts"
    PORTFOLIO_TRACKING = "portfolio_tracking"
    TIMING_SHADOW = "timing_shadow"
    EVENT_FEED = "event_feed"
    PENDING_TASKS = "pending_tasks"
    ACTIVE_FAILURES = "active_failures"


class DeskSectionStatus(StrEnum):
    """Server-owned data facts.  The client adds ``loading`` and ``error``."""

    READY = "ready"
    PARTIAL = "partial"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


SECTION_ORDER: tuple[DeskSectionKey, ...] = (
    DeskSectionKey.DATA_HEALTH,
    DeskSectionKey.SCREEN_SHIFTS,
    DeskSectionKey.PORTFOLIO_TRACKING,
    DeskSectionKey.TIMING_SHADOW,
    DeskSectionKey.EVENT_FEED,
    DeskSectionKey.PENDING_TASKS,
    DeskSectionKey.ACTIVE_FAILURES,
)


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


@dataclass(frozen=True)
class DeskBlocker:
    """Why a section cannot serve its full contract.

    Mirrors the shape of the research workspace blocker so the frontend renders
    both with one component, while keeping the two domains decoupled.
    """

    code: str
    reason: str
    affected_binding: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.code, "code")
        _text(self.reason, "reason")
        _text(self.affected_binding, "affected_binding")
        ids = tuple(self.evidence_ids)
        if any(not isinstance(value, str) or not value.strip() for value in ids):
            raise ValueError("evidence_ids must contain non-empty text")
        object.__setattr__(self, "evidence_ids", ids)


@dataclass(frozen=True)
class DeskSection:
    """One desk domain with its own status, reasons and coverage."""

    key: DeskSectionKey
    status: DeskSectionStatus
    title: str
    blockers: tuple[DeskBlocker, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)
    payload: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, DeskSectionKey):
            raise TypeError("key must be a DeskSectionKey")
        if not isinstance(self.status, DeskSectionStatus):
            raise TypeError("status must be a DeskSectionStatus")
        _text(self.title, "title")
        blockers = tuple(self.blockers)
        if any(not isinstance(value, DeskBlocker) for value in blockers):
            raise TypeError("blockers must contain DeskBlocker values")
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "coverage", dict(self.coverage))

        if self.status is DeskSectionStatus.PARTIAL and not (self.coverage or blockers):
            # A bare "partial" tells the operator nothing actionable.
            raise ValueError(
                f"section {self.key.value} is partial and must declare coverage or a blocker"
            )
        if self.status is DeskSectionStatus.UNAVAILABLE and not blockers:
            raise ValueError(
                f"section {self.key.value} is unavailable and must declare a blocker"
            )
        if self.status in (DeskSectionStatus.READY, DeskSectionStatus.PARTIAL):
            if self.payload is None:
                raise ValueError(f"section {self.key.value} is {self.status.value} and needs a payload")
        elif self.payload is not None:
            raise ValueError(
                f"section {self.key.value} is {self.status.value} and must not carry a payload"
            )


@dataclass(frozen=True)
class DeskProjection:
    """The whole desk.  Always seven sections, always in prototype order."""

    sections: tuple[DeskSection, ...]

    def __post_init__(self) -> None:
        sections = tuple(self.sections)
        if any(not isinstance(value, DeskSection) for value in sections):
            raise TypeError("sections must contain DeskSection values")
        keys = tuple(value.key for value in sections)
        if len(keys) != len(set(keys)):
            raise ValueError("desk sections must be unique")
        if set(keys) != set(SECTION_ORDER):
            # The skeleton is stable: a section reports unavailable, it never
            # disappears, so the page never silently loses a domain.
            raise ValueError("desk projection must carry all seven sections")
        order = {key: index for index, key in enumerate(SECTION_ORDER)}
        object.__setattr__(
            self,
            "sections",
            tuple(sorted(sections, key=lambda value: order[value.key])),
        )

    def section(self, key: DeskSectionKey) -> DeskSection:
        for value in self.sections:
            if value.key is key:
                return value
        raise KeyError(key)


__all__ = [
    "SECTION_ORDER",
    "DeskBlocker",
    "DeskProjection",
    "DeskSection",
    "DeskSectionKey",
    "DeskSectionStatus",
]
