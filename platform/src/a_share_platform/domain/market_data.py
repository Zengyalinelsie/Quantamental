"""Raw A-share market data, corporate action, and calendar contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum

from .pit import DataTrustState
from .security_master import Exchange, ListingState, SpecialTreatment


class PriceAdjustment(str, Enum):
    UNADJUSTED = "unadjusted"


class PriceLimitStatus(str, Enum):
    NOT_AT_LIMIT = "not_at_limit"
    LIMIT_UP = "limit_up"
    LIMIT_DOWN = "limit_down"
    LOCKED_UP = "locked_up"
    LOCKED_DOWN = "locked_down"


class CorporateActionType(str, Enum):
    CASH_DIVIDEND = "cash_dividend"
    BONUS_SHARE = "bonus_share"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    RIGHTS_ISSUE = "rights_issue"


class MarketDataUnavailable(LookupError):
    """Raised when a required market observation is unavailable."""


class MarketDataConflict(RuntimeError):
    """Raised when providers disagree and no selection rule has resolved the conflict."""


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _decimal(value: Decimal, field: str, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise TypeError(f"{field} must be a finite Decimal")
    if positive and value <= 0:
        raise ValueError(f"{field} must be positive")
    if not positive and value < 0:
        raise ValueError(f"{field} must not be negative")
    return value


def _interval(valid_from: date, valid_to: date | None) -> None:
    if not isinstance(valid_from, date):
        raise TypeError("effective_from must be a date")
    if valid_to is not None and (not isinstance(valid_to, date) or valid_to <= valid_from):
        raise ValueError("effective_to must be later than effective_from")


def _visible(valid_from: date, valid_to: date | None, as_of: date) -> bool:
    return valid_from <= as_of and (valid_to is None or as_of < valid_to)


@dataclass(frozen=True)
class DailyBar:
    listing_id: str
    exchange: Exchange
    session_date: date
    currency: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal
    volume_shares: int
    amount: Decimal
    adjustment: PriceAdjustment
    source_id: str
    dataset_version_id: str
    trust_state: DataTrustState

    def __post_init__(self) -> None:
        _required(self.listing_id, "listing_id")
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "currency", self.currency.upper())
        for value, field in (
            (self.open, "open"),
            (self.high, "high"),
            (self.low, "low"),
            (self.close, "close"),
            (self.previous_close, "previous_close"),
        ):
            _decimal(value, field, positive=True)
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be at least open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be at most open, high, and close")
        if type(self.volume_shares) is not int or self.volume_shares < 0:
            raise ValueError("volume_shares must be a non-negative integer")
        _decimal(self.amount, "amount")
        object.__setattr__(self, "adjustment", PriceAdjustment(self.adjustment))
        if self.adjustment is not PriceAdjustment.UNADJUSTED:
            raise ValueError("DailyBar stores only raw unadjusted prices")
        _required(self.source_id, "source_id")
        _required(self.dataset_version_id, "dataset_version_id")
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))


@dataclass(frozen=True)
class AdjustmentFactor:
    listing_id: str
    session_date: date
    multiplier: Decimal
    source_id: str
    dataset_version_id: str
    trust_state: DataTrustState

    def __post_init__(self) -> None:
        _required(self.listing_id, "listing_id")
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        _decimal(self.multiplier, "multiplier", positive=True)
        _required(self.source_id, "source_id")
        _required(self.dataset_version_id, "dataset_version_id")
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))


@dataclass(frozen=True)
class DailyMarketState:
    listing_id: str
    session_date: date
    is_trading: bool
    is_suspended: bool
    source_id: str
    dataset_version_id: str
    trust_state: DataTrustState
    listing_state: ListingState | None
    special_treatment: SpecialTreatment | None

    def __post_init__(self) -> None:
        _required(self.listing_id, "listing_id")
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        if type(self.is_trading) is not bool or type(self.is_suspended) is not bool:
            raise TypeError("trading and suspension flags must be booleans")
        if self.is_trading and self.is_suspended:
            raise ValueError("a session cannot be both trading and suspended")
        _required(self.source_id, "source_id")
        _required(self.dataset_version_id, "dataset_version_id")
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        if self.listing_state is not None:
            object.__setattr__(self, "listing_state", ListingState(self.listing_state))
        if self.special_treatment is not None:
            object.__setattr__(
                self,
                "special_treatment",
                SpecialTreatment(self.special_treatment),
            )
        if self.listing_state is ListingState.TERMINATED and self.is_trading:
            raise ValueError("a terminated listing cannot be trading")


@dataclass(frozen=True)
class PriceLimit:
    listing_id: str
    session_date: date
    lower: Decimal
    upper: Decimal
    source_id: str

    def __post_init__(self) -> None:
        _required(self.listing_id, "listing_id")
        if not isinstance(self.session_date, date):
            raise TypeError("session_date must be a date")
        _decimal(self.lower, "lower", positive=True)
        _decimal(self.upper, "upper", positive=True)
        if self.lower > self.upper:
            raise ValueError("lower price limit cannot exceed upper price limit")
        _required(self.source_id, "source_id")

    def status_for(self, bar: DailyBar) -> PriceLimitStatus:
        if bar.close == self.upper:
            if bar.low == self.upper and bar.high == self.upper:
                return PriceLimitStatus.LOCKED_UP
            return PriceLimitStatus.LIMIT_UP
        if bar.close == self.lower:
            if bar.low == self.lower and bar.high == self.lower:
                return PriceLimitStatus.LOCKED_DOWN
            return PriceLimitStatus.LIMIT_DOWN
        return PriceLimitStatus.NOT_AT_LIMIT


@dataclass(frozen=True)
class ShareCapital:
    listing_id: str
    effective_from: date
    effective_to: date | None
    total_shares: Decimal
    circulating_shares: Decimal | None
    free_float_shares: Decimal | None
    source_id: str
    dataset_version_id: str

    def __post_init__(self) -> None:
        _required(self.listing_id, "listing_id")
        _interval(self.effective_from, self.effective_to)
        _decimal(self.total_shares, "total_shares", positive=True)
        if self.circulating_shares is not None:
            _decimal(self.circulating_shares, "circulating_shares")
            if self.circulating_shares > self.total_shares:
                raise ValueError("circulating_shares cannot exceed total_shares")
        if self.free_float_shares is not None:
            _decimal(self.free_float_shares, "free_float_shares")
            if self.circulating_shares is None:
                raise ValueError("free_float_shares requires circulating_shares")
            if self.free_float_shares > self.circulating_shares:
                raise ValueError("free_float_shares cannot exceed circulating_shares")
        _required(self.source_id, "source_id")
        _required(self.dataset_version_id, "dataset_version_id")


@dataclass(frozen=True)
class CorporateAction:
    action_id: str
    listing_id: str
    action_type: CorporateActionType
    ex_date: date
    record_date: date
    cash_per_share: Decimal | None
    share_ratio: Decimal | None
    subscription_price: Decimal | None
    currency: str
    source_id: str

    def __post_init__(self) -> None:
        _required(self.action_id, "action_id")
        _required(self.listing_id, "listing_id")
        object.__setattr__(self, "action_type", CorporateActionType(self.action_type))
        if not isinstance(self.ex_date, date) or not isinstance(self.record_date, date):
            raise TypeError("corporate action dates must be dates")
        if self.record_date > self.ex_date:
            raise ValueError("record_date cannot follow ex_date")
        if self.cash_per_share is not None:
            _decimal(self.cash_per_share, "cash_per_share", positive=True)
        if self.share_ratio is not None:
            _decimal(self.share_ratio, "share_ratio", positive=True)
        if self.subscription_price is not None:
            _decimal(self.subscription_price, "subscription_price", positive=True)
        if self.action_type is CorporateActionType.CASH_DIVIDEND and self.cash_per_share is None:
            raise ValueError("cash dividend requires cash_per_share")
        ratio_types = {
            CorporateActionType.BONUS_SHARE,
            CorporateActionType.SPLIT,
            CorporateActionType.REVERSE_SPLIT,
        }
        if self.action_type in ratio_types and self.share_ratio is None:
            raise ValueError(f"{self.action_type.value} requires share_ratio")
        if self.action_type is CorporateActionType.RIGHTS_ISSUE and (
            self.share_ratio is None or self.subscription_price is None
        ):
            raise ValueError("rights issue requires share_ratio and subscription_price")
        if not isinstance(self.currency, str) or len(self.currency) != 3:
            raise ValueError("currency must be an ISO 4217 code")
        object.__setattr__(self, "currency", self.currency.upper())
        _required(self.source_id, "source_id")


@dataclass(frozen=True)
class CalendarDay:
    exchange: Exchange
    calendar_date: date
    is_open: bool
    closure_reason: str | None
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        if not isinstance(self.calendar_date, date):
            raise TypeError("calendar_date must be a date")
        if not self.is_open and not str(self.closure_reason or "").strip():
            raise ValueError("closed calendar day requires a reason")
        _required(self.source_id, "source_id")


@dataclass(frozen=True)
class ExchangeCalendar:
    exchange: Exchange
    days: tuple[CalendarDay, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "exchange", Exchange(self.exchange))
        object.__setattr__(self, "days", tuple(self.days))
        dates = [item.calendar_date for item in self.days]
        if len(dates) != len(set(dates)):
            raise ValueError("calendar dates must be unique")
        if any(item.exchange is not self.exchange for item in self.days):
            raise ValueError("calendar day exchange does not match calendar")

    def is_session(self, calendar_date: date) -> bool:
        day = next((item for item in self.days if item.calendar_date == calendar_date), None)
        if day is None:
            raise MarketDataUnavailable(f"calendar has no observation for {calendar_date}")
        return day.is_open

    def next_session(self, after: date) -> date:
        candidates = sorted(
            item.calendar_date
            for item in self.days
            if item.is_open and item.calendar_date > after
        )
        if not candidates:
            raise MarketDataUnavailable(f"calendar has no known session after {after}")
        return candidates[0]


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    severity: str
    listing_id: str
    session_date: date
    detail: str


@dataclass(frozen=True)
class MarketDataQualityReport:
    issues: tuple[DataQualityIssue, ...]


@dataclass(frozen=True)
class MarketDataCatalog:
    bars: tuple[DailyBar, ...]
    factors: tuple[AdjustmentFactor, ...]
    states: tuple[DailyMarketState, ...]
    price_limits: tuple[PriceLimit, ...]
    share_capital: tuple[ShareCapital, ...]
    corporate_actions: tuple[CorporateAction, ...]
    calendars: tuple[ExchangeCalendar, ...]

    def __post_init__(self) -> None:
        for field in (
            "bars",
            "factors",
            "states",
            "price_limits",
            "share_capital",
            "corporate_actions",
            "calendars",
        ):
            object.__setattr__(self, field, tuple(getattr(self, field)))
        exchanges = [calendar.exchange for calendar in self.calendars]
        if len(exchanges) != len(set(exchanges)):
            raise ValueError("only one calendar per exchange is allowed")

    @classmethod
    def empty(cls) -> MarketDataCatalog:
        return cls((), (), (), (), (), (), ())

    def bars_for(self, listing_id: str, session_date: date) -> tuple[DailyBar, ...]:
        return tuple(
            bar
            for bar in self.bars
            if bar.listing_id == listing_id and bar.session_date == session_date
        )

    def select_bar(self, listing_id: str, session_date: date) -> DailyBar:
        rows = self.bars_for(listing_id, session_date)
        if not rows:
            raise MarketDataUnavailable(f"daily bar unavailable for {listing_id}/{session_date}")
        values = {self._bar_value_key(row) for row in rows}
        if len(values) > 1:
            raise MarketDataConflict(f"conflicting daily bars for {listing_id}/{session_date}")
        return min(rows, key=lambda row: row.source_id)

    def adjusted_close(self, listing_id: str, session_date: date) -> Decimal:
        bar = self.select_bar(listing_id, session_date)
        factors = tuple(
            factor
            for factor in self.factors
            if factor.listing_id == listing_id and factor.session_date == session_date
        )
        if not factors:
            raise MarketDataUnavailable(
                f"adjustment factor unavailable for {listing_id}/{session_date}"
            )
        multipliers = {factor.multiplier for factor in factors}
        if len(multipliers) > 1:
            raise MarketDataConflict(
                f"conflicting adjustment factors for {listing_id}/{session_date}"
            )
        return bar.close * factors[0].multiplier

    def price_limit_status(self, listing_id: str, session_date: date) -> PriceLimitStatus:
        bar = self.select_bar(listing_id, session_date)
        limits = tuple(
            item
            for item in self.price_limits
            if item.listing_id == listing_id and item.session_date == session_date
        )
        if not limits:
            raise MarketDataUnavailable(f"price limit unavailable for {listing_id}/{session_date}")
        values = {(item.lower, item.upper) for item in limits}
        if len(values) > 1:
            raise MarketDataConflict(f"conflicting price limits for {listing_id}/{session_date}")
        return limits[0].status_for(bar)

    def share_capital_at(self, listing_id: str, as_of: date) -> ShareCapital:
        rows = tuple(
            item
            for item in self.share_capital
            if item.listing_id == listing_id
            and _visible(item.effective_from, item.effective_to, as_of)
        )
        if not rows:
            raise MarketDataUnavailable(f"share capital unavailable for {listing_id}/{as_of}")
        values = {
            (item.total_shares, item.circulating_shares, item.free_float_shares)
            for item in rows
        }
        if len(values) > 1:
            raise MarketDataConflict(f"conflicting share capital for {listing_id}/{as_of}")
        return min(rows, key=lambda row: row.source_id)

    def market_cap(self, listing_id: str, session_date: date) -> Decimal:
        return (
            self.select_bar(listing_id, session_date).close
            * self.share_capital_at(listing_id, session_date).total_shares
        )

    def calendar(self, exchange: Exchange | str) -> ExchangeCalendar:
        selected = Exchange(exchange)
        try:
            return next(item for item in self.calendars if item.exchange is selected)
        except StopIteration as error:
            raise MarketDataUnavailable(f"calendar unavailable for {selected.value}") from error

    def quality_report(self) -> MarketDataQualityReport:
        issues: list[DataQualityIssue] = []
        keys = sorted({(bar.listing_id, bar.session_date) for bar in self.bars})
        for listing_id, session_date in keys:
            rows = self.bars_for(listing_id, session_date)
            if len({self._bar_value_key(row) for row in rows}) > 1:
                issues.append(
                    DataQualityIssue(
                        code="bar_conflict",
                        severity="error",
                        listing_id=listing_id,
                        session_date=session_date,
                        detail="providers returned different raw daily bars",
                    )
                )
        return MarketDataQualityReport(tuple(issues))

    @staticmethod
    def _bar_value_key(bar: DailyBar) -> tuple[object, ...]:
        return (
            bar.exchange,
            bar.currency,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.previous_close,
            bar.volume_shares,
            bar.amount,
            bar.adjustment,
        )
