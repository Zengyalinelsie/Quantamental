"""Optional Futu quote-only reader for explicit bounded research requests."""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, cast

from a_share_platform.domain.backfill import ProviderRetrievalMetadata

_A_SHARE_CODE = re.compile(r"^(SH|SZ)\.\d{6}$")


class FutuQuoteError(RuntimeError):
    """Raised when the optional quote endpoint cannot satisfy a read request."""


@dataclass(frozen=True)
class FutuQuoteRows:
    rows: tuple[Mapping[str, object], ...]
    metadata: ProviderRetrievalMetadata


class FutuQuoteDailyReader:
    """Read raw daily rows through the SDK's quote-only context.

    This reader never opens an account or execution context. Persistence is
    permitted only through the separately gated ``private_local_research``
    workflow and remains outside general ``raw_bulk_persistence``.
    """

    provider_id = "futu_quote"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        module_loader: Callable[[str], object] = importlib.import_module,
        clock: Callable[[], datetime],
    ) -> None:
        if not host.strip():
            raise ValueError("host must not be empty")
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        self._host = host
        self._port = port
        self._module_loader = module_loader
        self._clock = clock

    def fetch_raw_daily_rows(
        self,
        *,
        code: str,
        start_date: date,
        end_date: date,
    ) -> FutuQuoteRows:
        if _A_SHARE_CODE.fullmatch(code) is None:
            raise ValueError("Futu A-share code must use SH.000000 or SZ.000000 format")
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise TypeError("history boundaries must be dates")
        if end_date < start_date:
            raise ValueError("end_date cannot precede start_date")

        module = cast(Any, self._module_loader("futu"))
        context_factory = getattr(module, "OpenQuoteContext", None)
        if not callable(context_factory):
            raise FutuQuoteError("installed futu SDK does not expose OpenQuoteContext")
        context = context_factory(host=self._host, port=self._port)
        rows: list[Mapping[str, object]] = []
        page_key: object | None = None
        try:
            while True:
                response = context.request_history_kline(
                    code=code,
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    ktype=module.KLType.K_DAY,
                    autype=module.AuType.NONE,
                    max_count=1000,
                    page_req_key=page_key,
                )
                if not isinstance(response, tuple) or len(response) != 3:
                    raise FutuQuoteError("unexpected quote history response shape")
                return_code, frame, page_key = response
                if return_code != module.RET_OK:
                    raise FutuQuoteError(f"quote history request failed: {frame}")
                to_dict = getattr(frame, "to_dict", None)
                if not callable(to_dict):
                    raise FutuQuoteError("quote history response is not tabular")
                page = cast(list[dict[str, Any]], to_dict("records"))
                if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                    raise FutuQuoteError("quote history rows are malformed")
                rows.extend(cast(list[Mapping[str, object]], page))
                if page_key is None:
                    break
        finally:
            close = getattr(context, "close", None)
            if callable(close):
                close()

        retrieved_at = self._clock()
        cutoff = self._cutoff(rows)
        return FutuQuoteRows(
            rows=tuple(rows),
            metadata=ProviderRetrievalMetadata(
                provider_id=self.provider_id,
                retrieved_at=retrieved_at,
                cutoff_date=cutoff,
                adjustment_mode="unadjusted",
                units=(
                    ("open", "CNY/share"),
                    ("high", "CNY/share"),
                    ("low", "CNY/share"),
                    ("close", "CNY/share"),
                    ("last_close", "CNY/share"),
                    ("volume", "shares"),
                    ("turnover", "CNY"),
                ),
                warnings=(
                    "private local research persistence requires explicit user acknowledgement",
                    "external redistribution, strict historical, and production use are prohibited",
                    "retrieved_at and time_key do not establish PIT available_at",
                    "output trust ceiling is normalized_current",
                ),
            ),
        )

    @staticmethod
    def _cutoff(rows: list[Mapping[str, object]]) -> date | None:
        dates: list[date] = []
        for row in rows:
            value = row.get("time_key")
            if value is None:
                raise FutuQuoteError("time_key is missing from quote history row")
            text = str(value).strip()
            try:
                dates.append(date.fromisoformat(text[:10]))
            except ValueError as error:
                raise FutuQuoteError("time_key is not an ISO-compatible timestamp") from error
        return max(dates) if dates else None
