"""Versioned historical research and tradable-universe contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .security_master import (
    Board,
    Exchange,
    ListingState,
    SecurityMaster,
    SpecialTreatment,
)


class UniverseConflict(RuntimeError):
    """Raised when a version has ambiguous effective-dated membership."""


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _validate_interval(valid_from: date, valid_to: date | None) -> None:
    if not isinstance(valid_from, date):
        raise TypeError("valid_from must be a date")
    if valid_to is not None and (not isinstance(valid_to, date) or valid_to <= valid_from):
        raise ValueError("valid_to must be later than valid_from")


def _contains(valid_from: date, valid_to: date | None, as_of: date) -> bool:
    return valid_from <= as_of and (valid_to is None or as_of < valid_to)


def _overlaps(
    left_from: date,
    left_to: date | None,
    right_from: date,
    right_to: date | None,
) -> bool:
    return left_from < (right_to or date.max) and right_from < (left_to or date.max)


@dataclass(frozen=True)
class UniverseDefinition:
    definition_id: str
    name: str
    ruleset_version: str
    benchmark_id: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.definition_id, "definition_id"),
            (self.name, "name"),
            (self.ruleset_version, "ruleset_version"),
            (self.benchmark_id, "benchmark_id"),
        ):
            _required(value, field)


@dataclass(frozen=True)
class UniverseVersion:
    universe_version_id: str
    definition_id: str
    dataset_version_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        for value, field in (
            (self.universe_version_id, "universe_version_id"),
            (self.definition_id, "definition_id"),
            (self.dataset_version_id, "dataset_version_id"),
        ):
            _required(value, field)
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True)
class UniverseMembership:
    universe_version_id: str
    listing_id: str
    valid_from: date
    valid_to: date | None
    research_eligible: bool
    tradable_eligible: bool
    inclusion_reasons: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    benchmark_member: bool

    def __post_init__(self) -> None:
        _required(self.universe_version_id, "universe_version_id")
        _required(self.listing_id, "listing_id")
        _validate_interval(self.valid_from, self.valid_to)
        object.__setattr__(self, "inclusion_reasons", tuple(self.inclusion_reasons))
        object.__setattr__(self, "exclusion_reasons", tuple(self.exclusion_reasons))
        for reason in (*self.inclusion_reasons, *self.exclusion_reasons):
            _required(reason, "eligibility reason")
        if self.tradable_eligible and not self.research_eligible:
            raise ValueError("tradable eligibility requires research eligibility")
        if self.research_eligible and not self.inclusion_reasons:
            raise ValueError("research eligibility requires an inclusion reason")
        if not self.tradable_eligible and not self.exclusion_reasons:
            raise ValueError("non-tradable membership requires an exclusion reason")


@dataclass(frozen=True)
class UniverseRow:
    listing_id: str
    company_id: str | None
    security_id: str | None
    exchange: Exchange | None
    board: Board | None
    code: str | None
    name: str | None
    listed_on: date | None
    delisted_on: date | None
    industry_name: str | None
    listing_state: ListingState | None
    special_treatment: SpecialTreatment | None
    research_eligible: bool
    tradable_eligible: bool
    inclusion_reasons: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]
    benchmark_member: bool
    identity_resolved: bool


@dataclass(frozen=True)
class UniverseSnapshot:
    universe_version_id: str
    dataset_version_id: str
    as_of: date
    rows: tuple[UniverseRow, ...]

    @property
    def research_listing_ids(self) -> tuple[str, ...]:
        return tuple(row.listing_id for row in self.rows if row.research_eligible)

    @property
    def tradable_listing_ids(self) -> tuple[str, ...]:
        return tuple(row.listing_id for row in self.rows if row.tradable_eligible)


@dataclass(frozen=True)
class UniverseDiff:
    universe_version_id: str
    from_date: date
    to_date: date
    added_listing_ids: tuple[str, ...]
    removed_listing_ids: tuple[str, ...]
    changed_listing_ids: tuple[str, ...]


@dataclass(frozen=True)
class UniverseCoverageReport:
    universe_version_id: str
    as_of: date
    total_members: int
    identity_resolved: int
    research_eligible: int
    tradable_eligible: int
    identity_coverage: float | None


@dataclass(frozen=True)
class UniverseCatalog:
    definitions: tuple[UniverseDefinition, ...]
    versions: tuple[UniverseVersion, ...]
    memberships: tuple[UniverseMembership, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "definitions", tuple(self.definitions))
        object.__setattr__(self, "versions", tuple(self.versions))
        object.__setattr__(self, "memberships", tuple(self.memberships))
        definition_ids = self._unique(self.definitions, "definition_id")
        version_ids = self._unique(self.versions, "universe_version_id")
        for version in self.versions:
            if version.definition_id not in definition_ids:
                raise ValueError(f"unknown definition_id: {version.definition_id}")
        for membership in self.memberships:
            if membership.universe_version_id not in version_ids:
                raise ValueError(
                    f"unknown universe_version_id: {membership.universe_version_id}"
                )
        self._reject_overlaps()

    @classmethod
    def empty(cls) -> UniverseCatalog:
        return cls((), (), ())

    @staticmethod
    def _unique(records: tuple[object, ...], field: str) -> set[str]:
        values = [str(getattr(record, field)) for record in records]
        if len(values) != len(set(values)):
            raise UniverseConflict(f"duplicate {field}")
        return set(values)

    def _reject_overlaps(self) -> None:
        for index, left in enumerate(self.memberships):
            for right in self.memberships[index + 1 :]:
                if (
                    left.universe_version_id == right.universe_version_id
                    and left.listing_id == right.listing_id
                    and _overlaps(left.valid_from, left.valid_to, right.valid_from, right.valid_to)
                ):
                    raise UniverseConflict(
                        "overlapping membership intervals for "
                        f"{left.universe_version_id}/{left.listing_id}"
                    )

    def version(self, universe_version_id: str) -> UniverseVersion:
        try:
            return next(
                item
                for item in self.versions
                if item.universe_version_id == universe_version_id
            )
        except StopIteration as error:
            raise KeyError(f"unknown universe_version_id: {universe_version_id}") from error

    def snapshot(
        self,
        universe_version_id: str,
        as_of: date,
        security_master: SecurityMaster,
    ) -> UniverseSnapshot:
        version = self.version(universe_version_id)
        active = tuple(
            membership
            for membership in self.memberships
            if membership.universe_version_id == universe_version_id
            and _contains(membership.valid_from, membership.valid_to, as_of)
        )
        rows = tuple(
            sorted(
                (self._row(membership, as_of, security_master) for membership in active),
                key=lambda row: row.listing_id,
            )
        )
        return UniverseSnapshot(
            universe_version_id,
            version.dataset_version_id,
            as_of,
            rows,
        )

    def diff(
        self,
        universe_version_id: str,
        from_date: date,
        to_date: date,
        security_master: SecurityMaster,
    ) -> UniverseDiff:
        before = {
            row.listing_id: row
            for row in self.snapshot(universe_version_id, from_date, security_master).rows
        }
        after = {
            row.listing_id: row
            for row in self.snapshot(universe_version_id, to_date, security_master).rows
        }
        return UniverseDiff(
            universe_version_id=universe_version_id,
            from_date=from_date,
            to_date=to_date,
            added_listing_ids=tuple(sorted(after.keys() - before.keys())),
            removed_listing_ids=tuple(sorted(before.keys() - after.keys())),
            changed_listing_ids=tuple(
                sorted(key for key in before.keys() & after.keys() if before[key] != after[key])
            ),
        )

    def coverage(
        self,
        universe_version_id: str,
        as_of: date,
        security_master: SecurityMaster,
    ) -> UniverseCoverageReport:
        snapshot = self.snapshot(universe_version_id, as_of, security_master)
        total = len(snapshot.rows)
        resolved = sum(row.identity_resolved for row in snapshot.rows)
        return UniverseCoverageReport(
            universe_version_id=universe_version_id,
            as_of=as_of,
            total_members=total,
            identity_resolved=resolved,
            research_eligible=sum(row.research_eligible for row in snapshot.rows),
            tradable_eligible=sum(row.tradable_eligible for row in snapshot.rows),
            identity_coverage=None if total == 0 else resolved / total,
        )

    @staticmethod
    def _row(
        membership: UniverseMembership,
        as_of: date,
        security_master: SecurityMaster,
    ) -> UniverseRow:
        try:
            identity = security_master.snapshot(membership.listing_id, as_of)
        except KeyError:
            identity = None
        industry = None if identity is None or not identity.industries else identity.industries[0]
        return UniverseRow(
            listing_id=membership.listing_id,
            company_id=None if identity is None else identity.company_id,
            security_id=None if identity is None else identity.security_id,
            exchange=None if identity is None else identity.exchange,
            board=None if identity is None else identity.board,
            code=None if identity is None else identity.code,
            name=None if identity is None else identity.name,
            listed_on=None if identity is None else identity.listed_on,
            delisted_on=None if identity is None else identity.delisted_on,
            industry_name=None if industry is None else industry.industry_name,
            listing_state=None if identity is None else identity.listing_state,
            special_treatment=None if identity is None else identity.special_treatment,
            research_eligible=membership.research_eligible,
            tradable_eligible=membership.tradable_eligible,
            inclusion_reasons=membership.inclusion_reasons,
            exclusion_reasons=membership.exclusion_reasons,
            benchmark_member=membership.benchmark_member,
            identity_resolved=identity is not None,
        )
