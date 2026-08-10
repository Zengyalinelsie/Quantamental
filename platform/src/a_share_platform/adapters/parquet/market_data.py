"""DuckDB-backed partitioned Parquet storage for immutable market observations."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast
from urllib.parse import quote

import duckdb

from a_share_platform.domain.market_data import (
    AdjustmentFactor,
    DailyBar,
    MarketDataCatalog,
    PriceAdjustment,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import Exchange


class ParquetMarketDataStore:
    """Write immutable partitions and query them without loading provider SDKs."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write_bars(self, bars: Iterable[DailyBar]) -> tuple[Path, ...]:
        grouped: dict[tuple[str, Exchange, int], list[DailyBar]] = defaultdict(list)
        for bar in bars:
            grouped[(bar.dataset_version_id, bar.exchange, bar.session_date.year)].append(bar)
        targets = {
            key: self._bar_partition(*key)
            for key in grouped
        }
        self._reject_existing(targets.values())
        for key, rows in grouped.items():
            target = targets[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    """
                    CREATE TABLE daily_bars (
                        listing_id VARCHAR,
                        exchange VARCHAR,
                        session_date DATE,
                        currency VARCHAR,
                        open DECIMAL(38, 10),
                        high DECIMAL(38, 10),
                        low DECIMAL(38, 10),
                        close DECIMAL(38, 10),
                        previous_close DECIMAL(38, 10),
                        volume_shares BIGINT,
                        amount DECIMAL(38, 10),
                        adjustment VARCHAR,
                        source_id VARCHAR,
                        dataset_version_id VARCHAR,
                        trust_state VARCHAR
                    )
                    """
                )
                connection.executemany(
                    "INSERT INTO daily_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [self._bar_values(row) for row in rows],
                )
                connection.execute(
                    f"COPY daily_bars TO {self._sql_literal(target)} (FORMAT PARQUET)"
                )
            finally:
                connection.close()
        return tuple(sorted(targets.values()))

    def ensure_bars(self, bars: Iterable[DailyBar]) -> tuple[Path, ...]:
        """Write once, or prove an interrupted retry has identical content."""

        rows = tuple(bars)
        grouped: dict[tuple[str, Exchange, int], list[DailyBar]] = defaultdict(list)
        for bar in rows:
            grouped[(bar.dataset_version_id, bar.exchange, bar.session_date.year)].append(bar)
        targets = {key: self._bar_partition(*key) for key in grouped}
        existing = {key: path.exists() for key, path in targets.items()}
        if not any(existing.values()):
            return self.write_bars(rows)
        if not all(existing.values()):
            raise FileExistsError("partial partition set exists; manual reconciliation required")
        for key, expected in grouped.items():
            actual = self._read_bar_partition(targets[key])
            order = lambda row: (row.listing_id, row.session_date, row.source_id)
            if tuple(sorted(actual, key=order)) != tuple(sorted(expected, key=order)):
                raise FileExistsError(f"partition content differs: {targets[key]}")
        return tuple(sorted(targets.values()))

    def write_adjustment_factors(
        self,
        factors: Iterable[AdjustmentFactor],
    ) -> tuple[Path, ...]:
        grouped: dict[tuple[str, int], list[AdjustmentFactor]] = defaultdict(list)
        for factor in factors:
            grouped[(factor.dataset_version_id, factor.session_date.year)].append(factor)
        targets = {key: self._factor_partition(*key) for key in grouped}
        self._reject_existing(targets.values())
        for key, rows in grouped.items():
            target = targets[key]
            target.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(":memory:")
            try:
                connection.execute(
                    """
                    CREATE TABLE adjustment_factors (
                        listing_id VARCHAR,
                        session_date DATE,
                        multiplier DECIMAL(38, 10),
                        source_id VARCHAR,
                        dataset_version_id VARCHAR,
                        trust_state VARCHAR
                    )
                    """
                )
                connection.executemany(
                    "INSERT INTO adjustment_factors VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            row.listing_id,
                            row.session_date,
                            row.multiplier,
                            row.source_id,
                            row.dataset_version_id,
                            row.trust_state.value,
                        )
                        for row in rows
                    ],
                )
                connection.execute(
                    f"COPY adjustment_factors TO {self._sql_literal(target)} (FORMAT PARQUET)"
                )
            finally:
                connection.close()
        return tuple(sorted(targets.values()))

    def query_bars(
        self,
        listing_id: str,
        *,
        start: date,
        end: date,
        dataset_version_id: str,
    ) -> tuple[DailyBar, ...]:
        self._validate_range(start, end)
        root = self.root / "daily_bars" / self._dataset_partition(dataset_version_id)
        rows: list[DailyBar] = []
        connection = duckdb.connect(":memory:")
        try:
            for path in sorted(root.rglob("*.parquet")) if root.exists() else ():
                result = connection.execute(
                    """
                    SELECT listing_id, exchange, session_date, currency, open, high, low,
                           close, previous_close, volume_shares, amount, adjustment,
                           source_id, dataset_version_id, trust_state
                    FROM read_parquet(?)
                    WHERE listing_id = ? AND session_date BETWEEN ? AND ?
                    """,
                    (str(path), listing_id, start, end),
                ).fetchall()
                rows.extend(self._bar_from_row(row) for row in result)
        finally:
            connection.close()
        return tuple(sorted(rows, key=lambda row: (row.session_date, row.source_id)))

    def query_adjustment_factors(
        self,
        listing_id: str,
        *,
        start: date,
        end: date,
        dataset_version_id: str,
    ) -> tuple[AdjustmentFactor, ...]:
        self._validate_range(start, end)
        root = self.root / "adjustment_factors" / self._dataset_partition(dataset_version_id)
        rows: list[AdjustmentFactor] = []
        connection = duckdb.connect(":memory:")
        try:
            for path in sorted(root.rglob("*.parquet")) if root.exists() else ():
                result = connection.execute(
                    """
                    SELECT listing_id, session_date, multiplier, source_id,
                           dataset_version_id, trust_state
                    FROM read_parquet(?)
                    WHERE listing_id = ? AND session_date BETWEEN ? AND ?
                    """,
                    (str(path), listing_id, start, end),
                ).fetchall()
                rows.extend(
                    AdjustmentFactor(
                        listing_id=row[0],
                        session_date=row[1],
                        multiplier=row[2],
                        source_id=row[3],
                        dataset_version_id=row[4],
                        trust_state=DataTrustState(row[5]),
                    )
                    for row in result
                )
        finally:
            connection.close()
        return tuple(sorted(rows, key=lambda row: (row.session_date, row.source_id)))

    def adjusted_close(
        self,
        listing_id: str,
        session_date: date,
        *,
        dataset_version_id: str,
    ) -> Decimal:
        bars = self.query_bars(
            listing_id,
            start=session_date,
            end=session_date,
            dataset_version_id=dataset_version_id,
        )
        factors = self.query_adjustment_factors(
            listing_id,
            start=session_date,
            end=session_date,
            dataset_version_id=dataset_version_id,
        )
        return MarketDataCatalog(bars, factors, (), (), (), (), ()).adjusted_close(
            listing_id,
            session_date,
        )

    def _bar_partition(self, dataset_version_id: str, exchange: Exchange, year: int) -> Path:
        return (
            self.root
            / "daily_bars"
            / self._dataset_partition(dataset_version_id)
            / f"exchange={exchange.value}"
            / f"year={year}"
            / "part-00000.parquet"
        )

    def _factor_partition(self, dataset_version_id: str, year: int) -> Path:
        return (
            self.root
            / "adjustment_factors"
            / self._dataset_partition(dataset_version_id)
            / f"year={year}"
            / "part-00000.parquet"
        )

    @staticmethod
    def _dataset_partition(dataset_version_id: str) -> str:
        if not dataset_version_id.strip():
            raise ValueError("dataset_version_id must not be empty")
        return f"dataset_version_id={quote(dataset_version_id, safe='')}"

    @staticmethod
    def _reject_existing(paths: Iterable[Path]) -> None:
        existing = next((path for path in paths if path.exists()), None)
        if existing is not None:
            raise FileExistsError(f"partition already exists: {existing}")

    @staticmethod
    def _validate_range(start: date, end: date) -> None:
        if not isinstance(start, date) or not isinstance(end, date):
            raise TypeError("query bounds must be dates")
        if end < start:
            raise ValueError("query end cannot precede start")

    @staticmethod
    def _sql_literal(path: Path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    @staticmethod
    def _bar_values(bar: DailyBar) -> tuple[object, ...]:
        return (
            bar.listing_id,
            bar.exchange.value,
            bar.session_date,
            bar.currency,
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.previous_close,
            bar.volume_shares,
            bar.amount,
            bar.adjustment.value,
            bar.source_id,
            bar.dataset_version_id,
            bar.trust_state.value,
        )

    @staticmethod
    def _bar_from_row(row: tuple[object, ...]) -> DailyBar:
        return DailyBar(
            listing_id=str(row[0]),
            exchange=Exchange(str(row[1])),
            session_date=cast(date, row[2]),
            currency=str(row[3]),
            open=cast(Decimal, row[4]),
            high=cast(Decimal, row[5]),
            low=cast(Decimal, row[6]),
            close=cast(Decimal, row[7]),
            previous_close=cast(Decimal, row[8]),
            volume_shares=cast(int, row[9]),
            amount=cast(Decimal, row[10]),
            adjustment=PriceAdjustment(str(row[11])),
            source_id=str(row[12]),
            dataset_version_id=str(row[13]),
            trust_state=DataTrustState(str(row[14])),
        )

    @classmethod
    def _read_bar_partition(cls, path: Path) -> tuple[DailyBar, ...]:
        connection = duckdb.connect(":memory:")
        try:
            rows = connection.execute(
                """
                SELECT listing_id, exchange, session_date, currency, open, high, low,
                       close, previous_close, volume_shares, amount, adjustment,
                       source_id, dataset_version_id, trust_state
                FROM read_parquet(?)
                """,
                (str(path),),
            ).fetchall()
        finally:
            connection.close()
        return tuple(cls._bar_from_row(row) for row in rows)
