"""Provider-neutral staged payloads passed from source adapters to canonical sinks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from a_share_platform.domain.security_master import Exchange, SpecialTreatment

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
