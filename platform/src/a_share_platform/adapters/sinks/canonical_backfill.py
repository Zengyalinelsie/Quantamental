"""Canonical Parquet/PostgreSQL sink for staged private research backfills."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from a_share_platform.adapters.parquet.market_data import ParquetMarketDataStore
from a_share_platform.adapters.providers.backfill_payloads import (
    DailyObservationPayload,
    TradingCalendarPayload,
)
from a_share_platform.domain.backfill import BackfillBatch, BackfillDataDomain
from a_share_platform.domain.market_data import (
    DailyBar,
    DailyMarketState,
    PriceAdjustment,
)
from a_share_platform.domain.pit import DataTrustState


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class CanonicalSinkError(RuntimeError):
    """Raised when staged data cannot map to canonical persisted contracts."""


class PostgresListingResolver:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def __call__(self, code: str, as_of: date) -> str:
        exchange = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}[code[:2]]
        rows = self._connection.execute(
            """
            SELECT identifiers.listing_id
            FROM identifier_history AS identifiers
            JOIN listings ON listings.listing_id = identifiers.listing_id
            WHERE identifiers.kind = 'code'
              AND identifiers.value = %s
              AND identifiers.valid_from <= %s
              AND (identifiers.valid_to IS NULL OR %s < identifiers.valid_to)
              AND listings.exchange = %s
            ORDER BY identifiers.listing_id
            """,
            (code.split(".", 1)[1], as_of, as_of, exchange),
        ).fetchall()
        if len(rows) != 1:
            raise CanonicalSinkError(
                f"expected one effective listing for code={code}, as_of={as_of}; got {len(rows)}"
            )
        return str(rows[0][0])


class CanonicalBackfillSink:
    def __init__(
        self,
        *,
        connection: Connection,
        parquet_store: ParquetMarketDataStore,
        clock: Callable[[], datetime],
        listing_resolver: Callable[[str, date], str] | None = None,
    ) -> None:
        self._connection = connection
        self._parquet = parquet_store
        self._clock = clock
        self._listing_resolver = listing_resolver or PostgresListingResolver(connection)

    def persist(self, batch: BackfillBatch, *, dataset_version_id: str) -> None:
        if not dataset_version_id.strip():
            raise ValueError("dataset_version_id must not be empty")
        if batch.trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise CanonicalSinkError("private local sink accepts only normalized_current")
        if (
            batch.work_unit.domain is BackfillDataDomain.RAW_DAILY_BAR
            and isinstance(batch.payload, DailyObservationPayload)
        ):
            self._persist_daily(batch, batch.payload, dataset_version_id)
            return
        if (
            batch.work_unit.domain is BackfillDataDomain.TRADING_CALENDAR
            and isinstance(batch.payload, TradingCalendarPayload)
        ):
            self._persist_calendar(batch.payload)
            return
        raise CanonicalSinkError(
            f"payload does not implement domain={batch.work_unit.domain.value}"
        )

    def _persist_daily(
        self,
        batch: BackfillBatch,
        payload: DailyObservationPayload,
        dataset_version_id: str,
    ) -> None:
        bars: list[DailyBar] = []
        states: list[DailyMarketState] = []
        for row in payload.rows:
            listing_id = self._listing_resolver(row.code, row.session_date)
            states.append(
                DailyMarketState(
                    listing_id=listing_id,
                    session_date=row.session_date,
                    is_trading=row.is_trading,
                    is_suspended=not row.is_trading,
                    source_id=row.source_id,
                    dataset_version_id=dataset_version_id,
                    trust_state=DataTrustState.NORMALIZED_CURRENT,
                    listing_state=None,
                    special_treatment=row.special_treatment,
                )
            )
            if not row.is_trading:
                continue
            assert row.open is not None
            assert row.high is not None
            assert row.low is not None
            assert row.close is not None
            assert row.previous_close is not None
            assert row.volume_shares is not None
            assert row.amount is not None
            bars.append(
                DailyBar(
                    listing_id=listing_id,
                    exchange=row.exchange,
                    session_date=row.session_date,
                    currency=row.currency,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    previous_close=row.previous_close,
                    volume_shares=row.volume_shares,
                    amount=row.amount,
                    adjustment=PriceAdjustment.UNADJUSTED,
                    source_id=row.source_id,
                    dataset_version_id=dataset_version_id,
                    trust_state=DataTrustState.NORMALIZED_CURRENT,
                )
            )
        for state in states:
            self._connection.execute(
                """
                INSERT INTO daily_market_states (
                    listing_id, session_date, is_trading, is_suspended,
                    listing_state, special_treatment, source_id,
                    dataset_version_id, trust_state
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (listing_id, session_date, source_id, dataset_version_id)
                DO NOTHING
                """,
                (
                    state.listing_id,
                    state.session_date,
                    state.is_trading,
                    state.is_suspended,
                    None if state.listing_state is None else state.listing_state.value,
                    (
                        None
                        if state.special_treatment is None
                        else state.special_treatment.value
                    ),
                    state.source_id,
                    state.dataset_version_id,
                    state.trust_state.value,
                ),
            )
        paths = self._parquet.ensure_bars(bars) if bars else ()
        if len(paths) > 1:
            raise CanonicalSinkError("one checkpoint unexpectedly produced multiple partitions")
        for path in paths:
            self._save_partition(batch, dataset_version_id, path, len(bars))

    def _save_partition(
        self,
        batch: BackfillBatch,
        dataset_version_id: str,
        path: Path,
        row_count: int,
    ) -> None:
        partition_key = "|".join(
            (dataset_version_id, batch.work_unit.checkpoint_key, str(path))
        ).encode("utf-8")
        partition_id = f"partition:{hashlib.sha256(partition_key).hexdigest()[:24]}"
        self._connection.execute(
            """
            INSERT INTO market_data_partitions (
                partition_id, dataset_version_id, data_type, storage_uri,
                content_hash, exchange, start_date, end_date, row_count, created_at
            ) VALUES (%s, %s, 'daily_bar', %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (partition_id) DO NOTHING
            """,
            (
                partition_id,
                dataset_version_id,
                path.resolve().as_uri(),
                batch.content_hash,
                batch.work_unit.market,
                batch.work_unit.start_date,
                batch.work_unit.end_date,
                row_count,
                self._clock(),
            ),
        )

    def _persist_calendar(self, payload: TradingCalendarPayload) -> None:
        for row in payload.rows:
            self._connection.execute(
                """
                INSERT INTO exchange_calendar_days (
                    exchange, calendar_date, is_open, closure_reason, source_id
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (exchange, calendar_date, source_id) DO NOTHING
                """,
                (
                    row.exchange.value,
                    row.calendar_date,
                    row.is_open,
                    row.closure_reason,
                    row.source_id,
                ),
            )
