"""A-share company, security, listing, and effective-dated identity contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Exchange(str, Enum):
    XSHG = "XSHG"
    XSHE = "XSHE"
    XBSE = "XBSE"


class Board(str, Enum):
    MAIN = "main"
    STAR = "star"
    CHINEXT = "chinext"
    BSE = "bse"


class SecurityClass(str, Enum):
    A_SHARE = "a_share"
    B_SHARE = "b_share"
    H_SHARE = "h_share"


class IdentifierKind(str, Enum):
    CODE = "code"
    NAME = "name"


class ListingState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended_listing"
    TERMINATED = "terminated"


class SpecialTreatment(str, Enum):
    NONE = "none"
    ST = "st"
    STAR_ST = "star_st"


class SecurityMasterConflict(RuntimeError):
    """Raised when effective-dated identity records are ambiguous."""


def _require_id(value: str, field: str) -> str:
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
    left_end = left_to or date.max
    right_end = right_to or date.max
    return left_from < right_end and right_from < left_end


@dataclass(frozen=True)
class Company:
    company_id: str
    legal_name: str

    def __post_init__(self) -> None:
        _require_id(self.company_id, "company_id")
        _require_id(self.legal_name, "legal_name")


@dataclass(frozen=True)
class Security:
    security_id: str
    company_id: str
    security_class: SecurityClass
    currency: str

    def __post_init__(self) -> None:
        _require_id(self.security_id, "security_id")
        _require_id(self.company_id, "company_id")
        object.__setattr__(self, "security_class", SecurityClass(self.security_class))
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "currency", self.currency.upper())


@dataclass(frozen=True)
class Listing:
    listing_id: str
    security_id: str
    exchange: Exchange
    board: Board
    listed_on: date
    delisted_on: date | None = None

    def __post_init__(self) -> None:
        _require_id(self.listing_id, "listing_id")
        _require_id(self.security_id, "security_id")
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        object.__setattr__(self, "board", Board(self.board))
        if not isinstance(self.listed_on, date):
            raise TypeError("listed_on must be a date")
        if self.delisted_on is not None and self.delisted_on <= self.listed_on:
            raise ValueError("delisted_on must be later than listed_on")
        required_exchange = {
            Board.STAR: Exchange.XSHG,
            Board.CHINEXT: Exchange.XSHE,
            Board.BSE: Exchange.XBSE,
        }.get(self.board)
        if required_exchange is not None and self.exchange is not required_exchange:
            raise ValueError(f"{self.board.name} board requires {required_exchange.value}")
        if self.exchange is Exchange.XBSE and self.board is not Board.BSE:
            raise ValueError("XBSE listings require BSE board")


@dataclass(frozen=True)
class IdentifierHistory:
    listing_id: str
    kind: IdentifierKind
    value: str
    valid_from: date
    valid_to: date | None
    source_id: str

    def __post_init__(self) -> None:
        _require_id(self.listing_id, "listing_id")
        object.__setattr__(self, "kind", IdentifierKind(self.kind))
        _require_id(self.value, "value")
        _require_id(self.source_id, "source_id")
        _validate_interval(self.valid_from, self.valid_to)


@dataclass(frozen=True)
class OfficialIdentifierAlias:
    """An exchange/company-announced identity interval with public evidence."""

    listing_id: str
    kind: IdentifierKind
    value: str
    valid_from: date
    valid_to: date | None
    source_id: str
    evidence_url: str
    published_on: date

    def __post_init__(self) -> None:
        _require_id(self.listing_id, "listing_id")
        object.__setattr__(self, "kind", IdentifierKind(self.kind))
        _require_id(self.value, "value")
        _validate_interval(self.valid_from, self.valid_to)
        _require_id(self.source_id, "source_id")
        if not isinstance(self.evidence_url, str) or not self.evidence_url.startswith(
            "https://"
        ):
            raise ValueError("evidence_url must be a non-empty HTTPS URL")
        if not isinstance(self.published_on, date):
            raise TypeError("published_on must be a date")


@dataclass(frozen=True)
class ProviderIdentifierCorrection:
    """A provider-local identity correction that must never become a global alias."""

    provider_id: str
    listing_id: str
    kind: IdentifierKind
    observed_value: str
    valid_from: date
    valid_to: date | None
    source_id: str
    reason: str

    def __post_init__(self) -> None:
        _require_id(self.provider_id, "provider_id")
        _require_id(self.listing_id, "listing_id")
        object.__setattr__(self, "kind", IdentifierKind(self.kind))
        _require_id(self.observed_value, "observed_value")
        _validate_interval(self.valid_from, self.valid_to)
        _require_id(self.source_id, "source_id")
        _require_id(self.reason, "reason")


@dataclass(frozen=True)
class ListingStatePeriod:
    listing_id: str
    valid_from: date
    valid_to: date | None
    state: ListingState
    special_treatment: SpecialTreatment
    source_id: str

    def __post_init__(self) -> None:
        _require_id(self.listing_id, "listing_id")
        _validate_interval(self.valid_from, self.valid_to)
        object.__setattr__(self, "state", ListingState(self.state))
        object.__setattr__(
            self,
            "special_treatment",
            SpecialTreatment(self.special_treatment),
        )
        _require_id(self.source_id, "source_id")


@dataclass(frozen=True)
class IndustryMembership:
    security_id: str
    taxonomy: str
    industry_code: str | None
    industry_name: str
    valid_from: date
    valid_to: date | None
    source_id: str

    def __post_init__(self) -> None:
        for value, field in (
            (self.security_id, "security_id"),
            (self.taxonomy, "taxonomy"),
            (self.industry_name, "industry_name"),
            (self.source_id, "source_id"),
        ):
            _require_id(value, field)
        if self.industry_code is not None:
            _require_id(self.industry_code, "industry_code")
        _validate_interval(self.valid_from, self.valid_to)


@dataclass(frozen=True)
class SecurityIdentitySnapshot:
    company_id: str
    company_name: str
    security_id: str
    security_class: SecurityClass
    currency: str
    listing_id: str
    exchange: Exchange
    board: Board
    code: str | None
    name: str | None
    listed_on: date
    delisted_on: date | None
    listing_state: ListingState | None
    special_treatment: SpecialTreatment | None
    industries: tuple[IndustryMembership, ...]


@dataclass(frozen=True)
class SecurityMaster:
    companies: tuple[Company, ...]
    securities: tuple[Security, ...]
    listings: tuple[Listing, ...]
    identifiers: tuple[IdentifierHistory, ...]
    states: tuple[ListingStatePeriod, ...]
    industries: tuple[IndustryMembership, ...]

    def __post_init__(self) -> None:
        for field in (
            "companies",
            "securities",
            "listings",
            "identifiers",
            "states",
            "industries",
        ):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        company_ids = self._unique_ids(self.companies, "company_id")
        security_ids = self._unique_ids(self.securities, "security_id")
        listing_ids = self._unique_ids(self.listings, "listing_id")
        for security in self.securities:
            if security.company_id not in company_ids:
                raise ValueError(f"unknown company_id: {security.company_id}")
        for listing in self.listings:
            if listing.security_id not in security_ids:
                raise ValueError(f"unknown security_id: {listing.security_id}")
        for identifier in self.identifiers:
            if identifier.listing_id not in listing_ids:
                raise ValueError(f"unknown listing_id: {identifier.listing_id}")
        for state_record in self.states:
            if state_record.listing_id not in listing_ids:
                raise ValueError(f"unknown listing_id: {state_record.listing_id}")
        for membership in self.industries:
            if membership.security_id not in security_ids:
                raise ValueError(f"unknown security_id: {membership.security_id}")
        self._reject_overlapping_identifiers()
        self._reject_overlapping_states()
        self._reject_overlapping_industries()

    @classmethod
    def empty(cls) -> SecurityMaster:
        return cls((), (), (), (), (), ())

    @staticmethod
    def _unique_ids(records: tuple[object, ...], field: str) -> set[str]:
        values = [str(getattr(record, field)) for record in records]
        if len(values) != len(set(values)):
            raise SecurityMasterConflict(f"duplicate {field}")
        return set(values)

    def _reject_overlapping_identifiers(self) -> None:
        for index, left in enumerate(self.identifiers):
            for right in self.identifiers[index + 1 :]:
                if (
                    left.listing_id == right.listing_id
                    and left.kind is right.kind
                    and _overlaps(left.valid_from, left.valid_to, right.valid_from, right.valid_to)
                ):
                    raise SecurityMasterConflict(
                        f"overlapping identifier history for {left.listing_id}/{left.kind.value}"
                    )

    def _reject_overlapping_states(self) -> None:
        for index, left in enumerate(self.states):
            for right in self.states[index + 1 :]:
                if left.listing_id == right.listing_id and _overlaps(
                    left.valid_from,
                    left.valid_to,
                    right.valid_from,
                    right.valid_to,
                ):
                    raise SecurityMasterConflict(
                        f"overlapping listing state history for {left.listing_id}"
                    )

    def _reject_overlapping_industries(self) -> None:
        for index, left in enumerate(self.industries):
            for right in self.industries[index + 1 :]:
                if (
                    left.security_id == right.security_id
                    and left.taxonomy == right.taxonomy
                    and _overlaps(left.valid_from, left.valid_to, right.valid_from, right.valid_to)
                ):
                    raise SecurityMasterConflict(
                        f"overlapping industry history for {left.security_id}/{left.taxonomy}"
                    )

    def securities_for_company(self, company_id: str) -> tuple[Security, ...]:
        return tuple(item for item in self.securities if item.company_id == company_id)

    def company(self, company_id: str) -> Company:
        return self._company(company_id)

    def listings_for_security(self, security_id: str) -> tuple[Listing, ...]:
        return tuple(item for item in self.listings if item.security_id == security_id)

    def resolve_listing(
        self,
        exchange: Exchange,
        code: str,
        as_of: date,
    ) -> SecurityIdentitySnapshot | None:
        exchange = Exchange(exchange)
        matches = tuple(
            record
            for record in self.identifiers
            if record.kind is IdentifierKind.CODE
            and record.value == code
            and _contains(record.valid_from, record.valid_to, as_of)
            and self._listing(record.listing_id).exchange is exchange
        )
        if len(matches) > 1:
            raise SecurityMasterConflict(f"ambiguous listing for {exchange.value}/{code}/{as_of}")
        return None if not matches else self.snapshot(matches[0].listing_id, as_of)

    def snapshot(self, listing_id: str, as_of: date) -> SecurityIdentitySnapshot:
        listing = self._listing(listing_id)
        security = self._security(listing.security_id)
        company = self._company(security.company_id)
        return SecurityIdentitySnapshot(
            company_id=company.company_id,
            company_name=company.legal_name,
            security_id=security.security_id,
            security_class=security.security_class,
            currency=security.currency,
            listing_id=listing.listing_id,
            exchange=listing.exchange,
            board=listing.board,
            code=self._identifier_value(listing_id, IdentifierKind.CODE, as_of),
            name=self._identifier_value(listing_id, IdentifierKind.NAME, as_of),
            listed_on=listing.listed_on,
            delisted_on=listing.delisted_on,
            listing_state=self._listing_state(listing_id, as_of),
            special_treatment=self._special_treatment(listing_id, as_of),
            industries=tuple(
                membership
                for membership in self.industries
                if membership.security_id == security.security_id
                and _contains(membership.valid_from, membership.valid_to, as_of)
            ),
        )

    def snapshots(self, as_of: date) -> tuple[SecurityIdentitySnapshot, ...]:
        return tuple(
            self.snapshot(listing.listing_id, as_of)
            for listing in self.listings
            if listing.listed_on <= as_of
            and (listing.delisted_on is None or as_of <= listing.delisted_on)
        )

    def _identifier_value(
        self,
        listing_id: str,
        kind: IdentifierKind,
        as_of: date,
    ) -> str | None:
        records = tuple(
            record
            for record in self.identifiers
            if record.listing_id == listing_id and record.kind is kind
        )
        visible = tuple(
            record for record in records if _contains(record.valid_from, record.valid_to, as_of)
        )
        if visible:
            return visible[0].value
        prior = tuple(record for record in records if record.valid_from < as_of)
        return None if not prior else max(prior, key=lambda record: record.valid_from).value

    def _state_record(self, listing_id: str, as_of: date) -> ListingStatePeriod | None:
        visible = tuple(
            record
            for record in self.states
            if record.listing_id == listing_id
            and _contains(record.valid_from, record.valid_to, as_of)
        )
        if not visible:
            return None
        return visible[0]

    def _listing_state(self, listing_id: str, as_of: date) -> ListingState | None:
        record = self._state_record(listing_id, as_of)
        return None if record is None else record.state

    def _special_treatment(self, listing_id: str, as_of: date) -> SpecialTreatment | None:
        record = self._state_record(listing_id, as_of)
        return None if record is None else record.special_treatment

    def _company(self, company_id: str) -> Company:
        try:
            return next(item for item in self.companies if item.company_id == company_id)
        except StopIteration as error:
            raise KeyError(f"unknown company_id: {company_id}") from error

    def _security(self, security_id: str) -> Security:
        return next(item for item in self.securities if item.security_id == security_id)

    def _listing(self, listing_id: str) -> Listing:
        try:
            return next(item for item in self.listings if item.listing_id == listing_id)
        except StopIteration as error:
            raise KeyError(f"unknown listing_id: {listing_id}") from error
