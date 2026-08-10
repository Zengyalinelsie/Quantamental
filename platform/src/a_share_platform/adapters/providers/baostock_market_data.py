"""Baostock JSON normalization without importing or trusting its SDK at the core boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from a_share_platform.domain.market_data import (
    DailyBar,
    DailyMarketState,
    PriceAdjustment,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import Exchange, SpecialTreatment


class ProviderPayloadError(ValueError):
    """Raised when a provider row cannot satisfy the normalized contract."""


@dataclass(frozen=True)
class NormalizedDailyMarketObservation:
    bar: DailyBar | None
    state: DailyMarketState


class BaostockDailyBarNormalizer:
    """Normalize one Baostock history row while preserving missing values.

    Baostock's free current-normalized endpoint does not prove historical
    availability, so this adapter deliberately cannot emit ``pit_verified``.
    """

    source_id = "a_share_mcp_baostock"

    def normalize(
        self,
        row: Mapping[str, object],
        *,
        listing_id: str,
        exchange: Exchange,
        dataset_version_id: str,
    ) -> NormalizedDailyMarketObservation:
        session_date = self._date(row, "date")
        trading = self._flag(row, "tradestatus")
        is_st = self._optional_flag(row, "isST")
        state = DailyMarketState(
            listing_id=listing_id,
            session_date=session_date,
            is_trading=trading,
            is_suspended=not trading,
            source_id=self.source_id,
            dataset_version_id=dataset_version_id,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            listing_state=None,
            special_treatment=(
                None
                if is_st is None
                else SpecialTreatment.ST if is_st else SpecialTreatment.NONE
            ),
        )
        if not trading:
            return NormalizedDailyMarketObservation(None, state)
        bar = DailyBar(
            listing_id=listing_id,
            exchange=exchange,
            session_date=session_date,
            currency="CNY",
            open=self._decimal(row, "open"),
            high=self._decimal(row, "high"),
            low=self._decimal(row, "low"),
            close=self._decimal(row, "close"),
            previous_close=self._decimal(row, "preclose"),
            volume_shares=self._integer(row, "volume"),
            amount=self._decimal(row, "amount", allow_zero=True),
            adjustment=PriceAdjustment.UNADJUSTED,
            source_id=self.source_id,
            dataset_version_id=dataset_version_id,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
        )
        return NormalizedDailyMarketObservation(bar, state)

    @staticmethod
    def _text(row: Mapping[str, object], field: str) -> str:
        value = row.get(field)
        text = "" if value is None else str(value).strip()
        if not text:
            raise ProviderPayloadError(f"{field} is missing from provider payload")
        return text

    @classmethod
    def _date(cls, row: Mapping[str, object], field: str) -> date:
        try:
            return date.fromisoformat(cls._text(row, field))
        except ValueError as error:
            raise ProviderPayloadError(f"{field} is not an ISO date") from error

    @classmethod
    def _decimal(
        cls,
        row: Mapping[str, object],
        field: str,
        *,
        allow_zero: bool = False,
    ) -> Decimal:
        try:
            value = Decimal(cls._text(row, field))
        except InvalidOperation as error:
            raise ProviderPayloadError(f"{field} is not a decimal") from error
        if not value.is_finite() or value < 0 or (not allow_zero and value == 0):
            raise ProviderPayloadError(f"{field} is outside the normalized range")
        return value

    @classmethod
    def _integer(cls, row: Mapping[str, object], field: str) -> int:
        text = cls._text(row, field)
        try:
            value = int(text)
        except ValueError as error:
            raise ProviderPayloadError(f"{field} is not an integer") from error
        if value < 0:
            raise ProviderPayloadError(f"{field} must not be negative")
        return value

    @classmethod
    def _flag(cls, row: Mapping[str, object], field: str) -> bool:
        value = cls._text(row, field)
        if value not in {"0", "1"}:
            raise ProviderPayloadError(f"{field} must be 0 or 1")
        return value == "1"

    @classmethod
    def _optional_flag(cls, row: Mapping[str, object], field: str) -> bool | None:
        value = row.get(field)
        if value is None or not str(value).strip():
            return None
        return cls._flag(row, field)
