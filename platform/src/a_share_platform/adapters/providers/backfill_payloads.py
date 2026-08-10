"""Provider-neutral staged payloads passed from source adapters to canonical sinks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise

from a_share_platform.domain.security_master import (
    Board,
    Exchange,
    ListingState,
    SpecialTreatment,
)

_SYMBOL = re.compile(r"^(SH|SZ|BJ)\.\d{6}$")
_SYMBOL_EXCHANGE = {
    "SH": Exchange.XSHG,
    "SZ": Exchange.XSHE,
    "BJ": Exchange.XBSE,
}


def _text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _finite_decimal(
    value: Decimal,
    field: str,
    *,
    positive: bool,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{field} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _symbol_exchange(code: str, exchange: Exchange | str) -> Exchange:
    if _SYMBOL.fullmatch(code) is None:
        raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000")
    selected = Exchange(exchange)
    if _SYMBOL_EXCHANGE[code[:2]] is not selected:
        raise ValueError("code prefix and exchange disagree")
    return selected


def _unique_provider_records(
    rows: tuple[
        StagedShareCapitalObservation | StagedCorporateActionObservation,
        ...,
    ],
) -> None:
    keys = tuple((row.code, row.provider_record_id) for row in rows)
    if len(keys) != len(set(keys)):
        raise ValueError("payload contains duplicate provider records")


@dataclass(frozen=True)
class StagedSecurityIdentity:
    code: str
    company_legal_name: str
    security_name: str
    exchange: Exchange
    board: Board
    listed_on: date
    delisted_on: date | None
    listing_state: ListingState
    observed_on: date
    industry_taxonomy: str | None
    industry_code: str | None
    industry_name: str | None
    identity_source_id: str
    legal_name_source_id: str
    industry_source_id: str | None

    def __post_init__(self) -> None:
        if _SYMBOL.fullmatch(self.code) is None:
            raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000")
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        if _SYMBOL_EXCHANGE[self.code[:2]] is not self.exchange:
            raise ValueError("code prefix and exchange disagree")
        object.__setattr__(self, "board", Board(self.board))
        object.__setattr__(self, "listing_state", ListingState(self.listing_state))
        for value, field in (
            (self.company_legal_name, "company_legal_name"),
            (self.security_name, "security_name"),
            (self.identity_source_id, "identity_source_id"),
            (self.legal_name_source_id, "legal_name_source_id"),
        ):
            _text(value, field)
        if not isinstance(self.listed_on, date) or not isinstance(self.observed_on, date):
            raise TypeError("identity dates must be dates")
        if self.delisted_on is not None and self.delisted_on <= self.listed_on:
            raise ValueError("delisted_on must be later than listed_on")
        industry_values = (
            self.industry_taxonomy,
            self.industry_name,
            self.industry_source_id,
        )
        if any(value is not None for value in industry_values):
            if any(value is None for value in industry_values):
                raise ValueError("industry taxonomy, name, and source must be supplied together")
            _text(self.industry_taxonomy or "", "industry_taxonomy")
            _text(self.industry_name or "", "industry_name")
            _text(self.industry_source_id or "", "industry_source_id")
        if self.industry_code is not None:
            _text(self.industry_code, "industry_code")


@dataclass(frozen=True)
class SecurityMasterPayload:
    rows: tuple[StagedSecurityIdentity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if any(not isinstance(row, StagedSecurityIdentity) for row in self.rows):
            raise TypeError("security-master payload rows must be staged identities")


@dataclass(frozen=True)
class StagedUniverseMembership:
    code: str
    valid_from: date
    valid_to: date
    source_id: str

    def __post_init__(self) -> None:
        if _SYMBOL.fullmatch(self.code) is None:
            raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000")
        if not isinstance(self.valid_from, date) or not isinstance(self.valid_to, date):
            raise TypeError("membership boundaries must be dates")
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        _text(self.source_id, "source_id")


@dataclass(frozen=True)
class UniverseMembershipPayload:
    benchmark_code: str
    rows: tuple[StagedUniverseMembership, ...]

    def __post_init__(self) -> None:
        if self.benchmark_code not in {"000300", "000905"}:
            raise ValueError("benchmark_code must be 000300 or 000905")
        object.__setattr__(self, "rows", tuple(self.rows))
        if any(not isinstance(row, StagedUniverseMembership) for row in self.rows):
            raise TypeError("universe payload rows must be staged memberships")
        ordered = sorted(self.rows, key=lambda row: (row.code, row.valid_from))
        for left, right in pairwise(ordered):
            if left.code == right.code and right.valid_from < left.valid_to:
                raise ValueError("universe membership intervals must not overlap")


@dataclass(frozen=True)
class StagedDailyObservation:
    code: str
    exchange: Exchange
    session_date: date
    currency: str
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    previous_close: Decimal | None
    volume_shares: int | None
    amount: Decimal | None
    is_trading: bool
    special_treatment: SpecialTreatment | None
    source_id: str

    def __post_init__(self) -> None:
        if _SYMBOL.fullmatch(self.code) is None:
            raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000")
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        if _SYMBOL_EXCHANGE[self.code[:2]] is not self.exchange:
            raise ValueError("code prefix and exchange disagree")
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "currency", self.currency.upper())
        if type(self.is_trading) is not bool:
            raise TypeError("is_trading must be a boolean")
        if self.special_treatment is not None:
            object.__setattr__(
                self,
                "special_treatment",
                SpecialTreatment(self.special_treatment),
            )
        _text(self.source_id, "source_id")
        values = (
            self.open,
            self.high,
            self.low,
            self.close,
            self.previous_close,
            self.volume_shares,
            self.amount,
        )
        if not self.is_trading:
            if any(value is not None for value in values):
                raise ValueError("non-trading observations must not invent bar values")
            return
        if any(value is None for value in values):
            raise ValueError("trading observations require a complete raw bar")
        decimals = (self.open, self.high, self.low, self.close, self.previous_close)
        if any(
            not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            for value in decimals
        ):
            raise ValueError("trading prices must be positive finite Decimals")
        if type(self.volume_shares) is not int or self.volume_shares < 0:
            raise ValueError("volume_shares must be a non-negative integer")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount < 0:
            raise ValueError("amount must be a non-negative finite Decimal")
        assert self.high is not None
        assert self.low is not None
        assert self.open is not None
        assert self.close is not None
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be at least open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be at most open, high, and close")


@dataclass(frozen=True)
class DailyObservationPayload:
    rows: tuple[StagedDailyObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if any(not isinstance(row, StagedDailyObservation) for row in self.rows):
            raise TypeError("daily payload rows must be staged observations")


@dataclass(frozen=True)
class StagedTradingCalendarDay:
    exchange: Exchange
    calendar_date: date
    is_open: bool
    closure_reason: str | None
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        if not isinstance(self.calendar_date, date):
            raise TypeError("calendar_date must be a date")
        if type(self.is_open) is not bool:
            raise TypeError("is_open must be a boolean")
        if self.is_open and self.closure_reason is not None:
            raise ValueError("open calendar day cannot have a closure reason")
        if not self.is_open:
            _text(self.closure_reason or "", "closure_reason")
        _text(self.source_id, "source_id")


@dataclass(frozen=True)
class TradingCalendarPayload:
    rows: tuple[StagedTradingCalendarDay, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if any(not isinstance(row, StagedTradingCalendarDay) for row in self.rows):
            raise TypeError("calendar payload rows must be staged calendar days")


@dataclass(frozen=True)
class StagedShareCapitalObservation:
    """A dated provider observation, not a fabricated PIT validity interval."""

    code: str
    exchange: Exchange
    effective_on: date
    announced_on: date | None
    total_shares: Decimal
    circulating_shares: Decimal | None
    restricted_shares: Decimal | None
    free_float_shares: Decimal | None
    provider_record_id: str
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", _symbol_exchange(self.code, self.exchange))
        if not isinstance(self.effective_on, date):
            raise TypeError("effective_on must be a date")
        if self.announced_on is not None and not isinstance(self.announced_on, date):
            raise TypeError("announced_on must be a date or None")
        _finite_decimal(self.total_shares, "total_shares", positive=True)
        components = (
            (self.circulating_shares, "circulating_shares"),
            (self.restricted_shares, "restricted_shares"),
            (self.free_float_shares, "free_float_shares"),
        )
        for value, field in components:
            if value is not None:
                _finite_decimal(value, field, positive=False)
                if value > self.total_shares:
                    raise ValueError(f"{field} cannot exceed total_shares")
        if (
            self.circulating_shares is not None
            and self.restricted_shares is not None
            and self.circulating_shares + self.restricted_shares > self.total_shares
        ):
            raise ValueError("circulating and restricted shares cannot exceed total_shares")
        if self.free_float_shares is not None:
            if self.circulating_shares is None:
                raise ValueError("free_float_shares requires circulating_shares")
            if self.free_float_shares > self.circulating_shares:
                raise ValueError("free_float_shares cannot exceed circulating_shares")
        _text(self.provider_record_id, "provider_record_id")
        _text(self.source_id, "source_id")


@dataclass(frozen=True)
class ShareCapitalPayload:
    rows: tuple[StagedShareCapitalObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if any(not isinstance(row, StagedShareCapitalObservation) for row in self.rows):
            raise TypeError("share-capital payload rows must be staged observations")
        _unique_provider_records(self.rows)


@dataclass(frozen=True)
class StagedCorporateActionObservation:
    """Provider distribution terms kept separate until canonical mapping is approved."""

    code: str
    exchange: Exchange
    announced_on: date | None
    record_date: date | None
    ex_date: date | None
    cash_per_share: Decimal | None
    bonus_shares_per_share: Decimal | None
    capitalization_shares_per_share: Decimal | None
    rights_shares_per_share: Decimal | None
    rights_subscription_price: Decimal | None
    currency: str
    provider_record_id: str
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", _symbol_exchange(self.code, self.exchange))
        for date_value, date_field in (
            (self.announced_on, "announced_on"),
            (self.record_date, "record_date"),
            (self.ex_date, "ex_date"),
        ):
            if date_value is not None and not isinstance(date_value, date):
                raise TypeError(f"{date_field} must be a date or None")
        if (
            self.record_date is not None
            and self.ex_date is not None
            and self.record_date > self.ex_date
        ):
            raise ValueError("record_date cannot follow ex_date")
        terms = (
            (self.cash_per_share, "cash_per_share"),
            (self.bonus_shares_per_share, "bonus_shares_per_share"),
            (
                self.capitalization_shares_per_share,
                "capitalization_shares_per_share",
            ),
            (self.rights_shares_per_share, "rights_shares_per_share"),
            (self.rights_subscription_price, "rights_subscription_price"),
        )
        for term_value, term_field in terms:
            if term_value is not None:
                _finite_decimal(term_value, term_field, positive=True)
        if not any(value is not None for value, _field in terms):
            raise ValueError("corporate action requires at least one economic term")
        if (self.rights_shares_per_share is None) != (
            self.rights_subscription_price is None
        ):
            raise ValueError("rights issue requires both ratio and subscription price")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "currency", self.currency.upper())
        _text(self.provider_record_id, "provider_record_id")
        _text(self.source_id, "source_id")


@dataclass(frozen=True)
class CorporateActionPayload:
    rows: tuple[StagedCorporateActionObservation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", tuple(self.rows))
        if any(not isinstance(row, StagedCorporateActionObservation) for row in self.rows):
            raise TypeError("corporate-action payload rows must be staged observations")
        _unique_provider_records(self.rows)
