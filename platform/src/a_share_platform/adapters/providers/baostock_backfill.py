"""Executable BaoStock source for explicitly acknowledged private local research."""

from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillDataDomain,
    BackfillPlan,
    BackfillWorkUnit,
    DatasetQualityStatus,
    ProviderRetrievalMetadata,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import ProviderUse
from a_share_platform.domain.security_master import Exchange, SpecialTreatment

from .backfill_payloads import (
    DailyObservationPayload,
    StagedDailyObservation,
    StagedTradingCalendarDay,
    TradingCalendarPayload,
)

_FIELDS = (
    "date",
    "code",
    "open",
    "high",
    "low",
    "close",
    "preclose",
    "volume",
    "amount",
    "tradestatus",
    "isST",
)
_MARKET_PREFIX = {"XSHG": "SH", "XSHE": "SZ", "XBSE": "BJ"}
_EXCHANGES = {"XSHG": Exchange.XSHG, "XSHE": Exchange.XSHE, "XBSE": Exchange.XBSE}


class ProviderBackfillUnavailable(RuntimeError):
    """Raised when a source cannot satisfy an explicitly requested backfill domain."""


class BaostockBackfillSource:
    provider_id = "baostock_sdk"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        module_loader: Callable[[str], object] = importlib.import_module,
    ) -> None:
        self._clock = clock
        self._module_loader = module_loader

    def fetch(self, unit: BackfillWorkUnit, plan: BackfillPlan) -> BackfillBatch:
        if plan.provider_id != self.provider_id:
            raise ValueError("plan provider does not match BaoStock source")
        if plan.provider_use is not ProviderUse.PRIVATE_LOCAL_RESEARCH:
            raise ValueError("BaoStock executable source requires private_local_research use")
        if plan.output_trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("BaoStock source can emit only normalized_current")
        if unit.domain not in {
            BackfillDataDomain.RAW_DAILY_BAR,
            BackfillDataDomain.TRADING_CALENDAR,
        }:
            raise ProviderBackfillUnavailable(
                f"baostock_sdk does not implement domain={unit.domain.value}"
            )
        module = cast(Any, self._module_loader("baostock"))
        login = module.login()
        self._require_success(login, "login")
        payload: DailyObservationPayload | TradingCalendarPayload
        units: tuple[tuple[str, str], ...]
        dates: list[date]
        try:
            if unit.domain is BackfillDataDomain.RAW_DAILY_BAR:
                payload = self._daily_payload(module, unit, plan)
                units = (
                    ("open", "CNY/share"),
                    ("high", "CNY/share"),
                    ("low", "CNY/share"),
                    ("close", "CNY/share"),
                    ("preclose", "CNY/share"),
                    ("volume", "shares"),
                    ("amount", "CNY"),
                )
                dates = [row.session_date for row in payload.rows]
            else:
                payload = self._calendar_payload(module, unit)
                units = (("is_trading_day", "boolean"),)
                dates = [row.calendar_date for row in payload.rows]
        finally:
            module.logout()
        warnings = [
            "private local research only; external redistribution is prohibited",
            "provider retrieval time does not establish historical PIT availability",
            "output trust ceiling is normalized_current",
        ]
        rows = payload.rows
        if not rows:
            warnings.append("provider returned no rows for the requested work unit")
        retrieved_at = self._clock()
        return BackfillBatch(
            work_unit=unit,
            metadata=ProviderRetrievalMetadata(
                provider_id=self.provider_id,
                retrieved_at=retrieved_at,
                cutoff_date=max(dates) if dates else None,
                adjustment_mode=(
                    "unadjusted"
                    if unit.domain is BackfillDataDomain.RAW_DAILY_BAR
                    else "not_applicable"
                ),
                units=units,
                warnings=tuple(warnings),
            ),
            row_count=len(rows),
            rejected_rows=0,
            content_hash=self._content_hash(unit, payload),
            expected_rows=None,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            quality_status=(
                DatasetQualityStatus.PASSED if rows else DatasetQualityStatus.WARNED
            ),
            issue_counts=(() if rows else (("empty_provider_result", 1),)),
            warnings=(() if rows else ("empty provider result",)),
            payload=payload,
        )

    def _daily_payload(
        self,
        module: Any,
        unit: BackfillWorkUnit,
        plan: BackfillPlan,
    ) -> DailyObservationPayload:
        if unit.market is None:
            raise ProviderBackfillUnavailable("raw_daily_bar work unit requires a market")
        prefix = _MARKET_PREFIX[unit.market]
        if prefix == "BJ":
            raise ProviderBackfillUnavailable("BaoStock SDK does not support XBSE raw bars")
        observations: list[StagedDailyObservation] = []
        for symbol in (item for item in plan.symbols if item.startswith(prefix + ".")):
            result = module.query_history_k_data_plus(
                code=symbol.lower(),
                fields=",".join(_FIELDS),
                start_date=unit.start_date.isoformat(),
                end_date=unit.end_date.isoformat(),
                frequency="d",
                adjustflag="3",
            )
            self._require_success(result, f"raw daily bars for {symbol}")
            for row in self._result_rows(result):
                observations.append(self._daily_observation(row, unit.market))
        return DailyObservationPayload(tuple(observations))

    def _calendar_payload(
        self,
        module: Any,
        unit: BackfillWorkUnit,
    ) -> TradingCalendarPayload:
        if unit.market not in {"XSHG", "XSHE"}:
            raise ProviderBackfillUnavailable(
                f"BaoStock calendar does not support market={unit.market}"
            )
        result = module.query_trade_dates(
            start_date=unit.start_date.isoformat(),
            end_date=unit.end_date.isoformat(),
        )
        self._require_success(result, f"trading calendar for {unit.market}")
        exchange = _EXCHANGES[unit.market]
        rows: list[StagedTradingCalendarDay] = []
        for raw in self._result_rows(result):
            flag = self._flag(raw, "is_trading_day")
            rows.append(
                StagedTradingCalendarDay(
                    exchange=exchange,
                    calendar_date=self._date(raw, "calendar_date"),
                    is_open=flag,
                    closure_reason=None if flag else "provider_reported_closed",
                    source_id=self.provider_id,
                )
            )
        return TradingCalendarPayload(tuple(rows))

    def _daily_observation(
        self,
        row: Mapping[str, object],
        market: str,
    ) -> StagedDailyObservation:
        trading = self._flag(row, "tradestatus")
        special = SpecialTreatment.ST if self._flag(row, "isST") else SpecialTreatment.NONE
        code = self._text(row, "code").upper()
        exchange = _EXCHANGES[market]
        session_date = self._date(row, "date")
        if not trading:
            return StagedDailyObservation(
                code=code,
                exchange=exchange,
                session_date=session_date,
                currency="CNY",
                open=None,
                high=None,
                low=None,
                close=None,
                previous_close=None,
                volume_shares=None,
                amount=None,
                is_trading=False,
                special_treatment=special,
                source_id=self.provider_id,
            )
        return StagedDailyObservation(
            code=code,
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
            is_trading=True,
            special_treatment=special,
            source_id=self.provider_id,
        )

    @staticmethod
    def _result_rows(result: Any) -> tuple[Mapping[str, object], ...]:
        fields = tuple(str(item) for item in result.fields)
        rows: list[Mapping[str, object]] = []
        while result.next():
            values = result.get_row_data()
            if len(values) != len(fields):
                raise ProviderBackfillUnavailable("provider row and field counts disagree")
            rows.append(dict(zip(fields, values, strict=True)))
        return tuple(rows)

    @staticmethod
    def _require_success(result: Any, operation: str) -> None:
        if str(getattr(result, "error_code", "")) != "0":
            message = str(getattr(result, "error_msg", "unknown provider error"))
            raise ProviderBackfillUnavailable(f"{operation} failed: {message}")

    @staticmethod
    def _text(row: Mapping[str, object], field: str) -> str:
        value = row.get(field)
        text = "" if value is None else str(value).strip()
        if not text:
            raise ProviderBackfillUnavailable(f"{field} is missing from provider payload")
        return text

    @classmethod
    def _date(cls, row: Mapping[str, object], field: str) -> date:
        try:
            return date.fromisoformat(cls._text(row, field))
        except ValueError as error:
            raise ProviderBackfillUnavailable(f"{field} is not an ISO date") from error

    @classmethod
    def _flag(cls, row: Mapping[str, object], field: str) -> bool:
        value = cls._text(row, field)
        if value not in {"0", "1"}:
            raise ProviderBackfillUnavailable(f"{field} must be 0 or 1")
        return value == "1"

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
            raise ProviderBackfillUnavailable(f"{field} is not a decimal") from error
        if not value.is_finite() or value < 0 or (value == 0 and not allow_zero):
            raise ProviderBackfillUnavailable(f"{field} is outside the normalized range")
        return value

    @classmethod
    def _integer(cls, row: Mapping[str, object], field: str) -> int:
        try:
            value = int(cls._text(row, field))
        except ValueError as error:
            raise ProviderBackfillUnavailable(f"{field} is not an integer") from error
        if value < 0:
            raise ProviderBackfillUnavailable(f"{field} cannot be negative")
        return value

    @staticmethod
    def _content_hash(unit: BackfillWorkUnit, payload: object) -> str:
        document = json.dumps(
            {"checkpoint_key": unit.checkpoint_key, "payload": payload},
            default=str,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(document).hexdigest()}"
