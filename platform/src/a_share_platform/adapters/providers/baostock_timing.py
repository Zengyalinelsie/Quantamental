"""Guarded BaoStock source for current CSI benchmark closes."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from itertools import pairwise
from typing import Any, cast

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing import (
    BenchmarkCloseBatch,
    BenchmarkCloseObservation,
)

from .baostock_guard import BaostockGuard

_PROVIDER_CODES = {
    "index:000300": "sh.000300",
    "index:000905": "sh.000905",
}
_FIELDS = ("date", "code", "close")


class TimingBenchmarkSourceError(RuntimeError):
    """Raised when a benchmark response cannot satisfy the baseline contract."""


class BaostockTimingBenchmarkSource:
    """Read 21 unadjusted closes without opening any account context."""

    provider_id = "baostock_sdk"

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        module_loader: Callable[[str], object] = importlib.import_module,
        baostock_guard: BaostockGuard | None = None,
    ) -> None:
        self._clock = clock
        self._module_loader = module_loader
        self._baostock_guard = baostock_guard or BaostockGuard()

    def fetch_recent_closes(
        self,
        *,
        benchmark_id: str,
        end_session: date,
    ) -> BenchmarkCloseBatch:
        provider_code = _PROVIDER_CODES.get(benchmark_id)
        if provider_code is None:
            raise ValueError("benchmark_id must be a supported CSI benchmark")
        if not isinstance(end_session, date) or isinstance(end_session, datetime):
            raise TypeError("end_session must be a date")

        module = cast(Any, self._module_loader("baostock"))
        with self._baostock_guard.session() as session:
            login = session.call("login", module.login)
            self._require_success(login, "login")
            try:
                result = session.call(
                    "query_history_k_data_plus",
                    partial(
                        module.query_history_k_data_plus,
                        code=provider_code,
                        fields=",".join(_FIELDS),
                        start_date=(end_session - timedelta(days=90)).isoformat(),
                        end_date=end_session.isoformat(),
                        frequency="d",
                        adjustflag="3",
                    ),
                )
                self._require_success(result, f"daily closes for {benchmark_id}")
                raw_rows = self._result_rows(result)
            finally:
                session.call("logout", module.logout)

        rows = tuple(
            self._observation(raw, benchmark_id=benchmark_id, provider_code=provider_code)
            for raw in raw_rows
        )
        if any(
            current.session_date <= previous.session_date
            for previous, current in pairwise(rows)
        ):
            raise TimingBenchmarkSourceError(
                "provider benchmark close dates must be strictly increasing"
            )
        if len(rows) < 21:
            raise TimingBenchmarkSourceError(
                "provider returned fewer than 21 benchmark closes"
            )
        selected = rows[-21:]
        if selected[-1].session_date != end_session:
            raise TimingBenchmarkSourceError(
                "provider did not return a complete close for the requested session"
            )
        return BenchmarkCloseBatch(
            benchmark_id=benchmark_id,
            rows=selected,
            provider_id=self.provider_id,
            retrieved_at=self._clock(),
            adjustment_mode="unadjusted",
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            data_mode=DataMode.CURRENT_RESEARCH,
        )

    @staticmethod
    def _result_rows(result: object) -> tuple[dict[str, str], ...]:
        fields = tuple(str(item) for item in getattr(result, "fields", ()))
        if fields != _FIELDS:
            raise TimingBenchmarkSourceError(
                f"unexpected benchmark fields: expected={_FIELDS}, got={fields}"
            )
        next_row = getattr(result, "next", None)
        get_row_data = getattr(result, "get_row_data", None)
        if not callable(next_row) or not callable(get_row_data):
            raise TimingBenchmarkSourceError("benchmark result is not iterable")
        rows: list[dict[str, str]] = []
        while next_row():
            values = tuple(str(item).strip() for item in get_row_data())
            if len(values) != len(fields):
                raise TimingBenchmarkSourceError("benchmark row width does not match fields")
            rows.append(dict(zip(fields, values, strict=True)))
        return tuple(rows)

    @staticmethod
    def _observation(
        row: Mapping[str, str],
        *,
        benchmark_id: str,
        provider_code: str,
    ) -> BenchmarkCloseObservation:
        if row.get("code") != provider_code:
            raise TimingBenchmarkSourceError("provider benchmark code does not match request")
        try:
            session_date = date.fromisoformat(row["date"])
        except (KeyError, ValueError) as error:
            raise TimingBenchmarkSourceError("provider benchmark date is invalid") from error
        try:
            close = Decimal(row["close"])
        except (KeyError, InvalidOperation) as error:
            raise TimingBenchmarkSourceError("provider benchmark close is invalid") from error
        try:
            return BenchmarkCloseObservation(
                benchmark_id=benchmark_id,
                session_date=session_date,
                unadjusted_close=close,
            )
        except (TypeError, ValueError) as error:
            raise TimingBenchmarkSourceError(str(error)) from error

    @staticmethod
    def _require_success(result: object, operation: str) -> None:
        error_code = str(getattr(result, "error_code", ""))
        if error_code != "0":
            error_message = str(getattr(result, "error_msg", "unknown provider error"))
            raise TimingBenchmarkSourceError(
                f"BaoStock {operation} failed: {error_code} {error_message}"
            )
