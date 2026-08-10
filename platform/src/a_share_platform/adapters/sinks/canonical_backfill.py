"""Canonical Parquet/PostgreSQL sink for staged private research backfills."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol, cast

from a_share_platform.adapters.parquet.market_data import ParquetMarketDataStore
from a_share_platform.adapters.providers.backfill_payloads import (
    DailyObservationPayload,
    SecurityMasterPayload,
    TradingCalendarPayload,
    UniverseMembershipPayload,
)
from a_share_platform.domain.backfill import BackfillBatch, BackfillDataDomain
from a_share_platform.domain.market_data import (
    DailyBar,
    DailyMarketState,
    PriceAdjustment,
)
from a_share_platform.domain.pit import DataTrustState


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


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


@dataclass(frozen=True)
class CanonicalUniverseVersion:
    universe_version_id: str
    definition_id: str
    dataset_version_id: str
    created_at: datetime
    trust_state: DataTrustState
    provider_id: str
    source_ids: tuple[str, ...]
    retrieved_at: datetime
    system_as_of: datetime
    available_at: datetime | None


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
        if (
            batch.work_unit.domain is BackfillDataDomain.SECURITY_MASTER
            and isinstance(batch.payload, SecurityMasterPayload)
        ):
            self._persist_security_master(batch.payload, dataset_version_id)
            return
        if (
            batch.work_unit.domain is BackfillDataDomain.UNIVERSE
            and isinstance(batch.payload, UniverseMembershipPayload)
        ):
            self._persist_universe(batch, batch.payload, dataset_version_id)
            return
        raise CanonicalSinkError(
            f"payload does not implement domain={batch.work_unit.domain.value}"
        )

    def get_universe_version(
        self,
        universe_version_id: str,
        *,
        require_pit_verified: bool,
    ) -> CanonicalUniverseVersion | None:
        """Read complete lineage and make the strict-PIT boundary explicit."""

        if not universe_version_id.strip():
            raise ValueError("universe_version_id must not be empty")
        row = self._connection.execute(
            """
            SELECT universe_version_id, definition_id, dataset_version_id,
                   created_at, trust_state, provider_id, source_ids,
                   retrieved_at, system_as_of, available_at
            FROM universe_versions
            WHERE universe_version_id = %s
            """,
            (universe_version_id,),
        ).fetchone()
        if row is None:
            return None
        record = self._universe_version_from_row(row)
        if require_pit_verified and record.trust_state is not DataTrustState.PIT_VERIFIED:
            raise CanonicalSinkError(
                "strict PIT consumer rejected universe version with "
                f"trust_state={record.trust_state.value}"
            )
        if require_pit_verified and record.available_at is None:
            raise CanonicalSinkError(
                "strict PIT consumer requires an explicit available_at"
            )
        return record

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

    def _persist_security_master(
        self,
        payload: SecurityMasterPayload,
        dataset_version_id: str,
    ) -> None:
        for row in payload.rows:
            company_id, security_id, listing_id = self._identity_ids(
                row.exchange.value,
                row.code,
            )
            self._connection.execute(
                """
                INSERT INTO companies (
                    company_id, legal_name, legal_name_source_id, observed_on,
                    dataset_version_id, trust_state
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (company_id) DO UPDATE SET
                    legal_name = EXCLUDED.legal_name,
                    legal_name_source_id = EXCLUDED.legal_name_source_id,
                    observed_on = EXCLUDED.observed_on,
                    dataset_version_id = EXCLUDED.dataset_version_id,
                    trust_state = EXCLUDED.trust_state
                WHERE companies.observed_on IS NULL
                   OR companies.observed_on <= EXCLUDED.observed_on
                """,
                (
                    company_id,
                    row.company_legal_name,
                    row.legal_name_source_id,
                    row.observed_on,
                    dataset_version_id,
                    DataTrustState.NORMALIZED_CURRENT.value,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO securities (
                    security_id, company_id, security_class, currency
                ) VALUES (%s, %s, 'a_share', 'CNY')
                ON CONFLICT (security_id) DO NOTHING
                """,
                (security_id, company_id),
            )
            self._connection.execute(
                """
                INSERT INTO listings (
                    listing_id, security_id, exchange, board, listed_on, delisted_on
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (listing_id) DO UPDATE SET
                    delisted_on = COALESCE(EXCLUDED.delisted_on, listings.delisted_on)
                """,
                (
                    listing_id,
                    security_id,
                    row.exchange.value,
                    row.board.value,
                    row.listed_on,
                    row.delisted_on,
                ),
            )
            self._persist_identifier(
                listing_id=listing_id,
                kind="code",
                value=row.code.split(".", 1)[1],
                observed_on=row.observed_on,
                source_id=row.identity_source_id,
            )
            self._persist_identifier(
                listing_id=listing_id,
                kind="name",
                value=row.security_name,
                observed_on=row.observed_on,
                source_id=row.identity_source_id,
            )
            state_from = row.delisted_on or row.observed_on
            self._persist_listing_state(
                listing_id=listing_id,
                valid_from=state_from,
                state=row.listing_state.value,
                source_id=row.identity_source_id,
            )
            if row.industry_name is not None:
                assert row.industry_taxonomy is not None
                assert row.industry_source_id is not None
                self._persist_industry(
                    security_id=security_id,
                    taxonomy=row.industry_taxonomy,
                    industry_code=row.industry_code,
                    industry_name=row.industry_name,
                    observed_on=row.observed_on,
                    source_id=row.industry_source_id,
                )

    def _persist_identifier(
        self,
        *,
        listing_id: str,
        kind: str,
        value: str,
        observed_on: date,
        source_id: str,
    ) -> None:
        self._connection.execute(
            """
            UPDATE identifier_history
            SET valid_to = %s
            WHERE listing_id = %s AND kind = %s AND valid_to IS NULL
              AND valid_from < %s
            """,
            (observed_on, listing_id, kind, observed_on),
        )
        result = self._connection.execute(
            """
            INSERT INTO identifier_history (
                listing_id, kind, value, valid_from, valid_to, source_id
            )
            VALUES (%s, %s, %s, %s, NULL, %s)
            ON CONFLICT (listing_id, kind, valid_from) DO UPDATE SET
                identifier_history_id = identifier_history.identifier_history_id
            WHERE identifier_history.value = EXCLUDED.value
              AND identifier_history.valid_to IS NULL
              AND identifier_history.source_id = EXCLUDED.source_id
            RETURNING identifier_history_id
            """,
            (
                listing_id,
                kind,
                value,
                observed_on,
                source_id,
            ),
        )
        self._require_immutable_write(
            result,
            "identifier correction conflicts on the same effective date",
        )

    def _persist_listing_state(
        self,
        *,
        listing_id: str,
        valid_from: date,
        state: str,
        source_id: str,
    ) -> None:
        self._connection.execute(
            """
            UPDATE listing_state_periods
            SET valid_to = %s
            WHERE listing_id = %s AND valid_to IS NULL AND valid_from < %s
            """,
            (valid_from, listing_id, valid_from),
        )
        result = self._connection.execute(
            """
            INSERT INTO listing_state_periods (
                listing_id, valid_from, valid_to, state, special_treatment, source_id
            )
            VALUES (%s, %s, NULL, %s, %s, %s)
            ON CONFLICT (listing_id, valid_from) DO UPDATE SET
                listing_state_period_id = listing_state_periods.listing_state_period_id
            WHERE listing_state_periods.state = EXCLUDED.state
              AND listing_state_periods.special_treatment IS NOT DISTINCT FROM
                  EXCLUDED.special_treatment
              AND listing_state_periods.valid_to IS NULL
              AND listing_state_periods.source_id = EXCLUDED.source_id
            RETURNING listing_state_period_id
            """,
            (listing_id, valid_from, state, None, source_id),
        )
        self._require_immutable_write(
            result,
            "listing-state correction conflicts on the same effective date",
        )

    def _persist_industry(
        self,
        *,
        security_id: str,
        taxonomy: str,
        industry_code: str | None,
        industry_name: str,
        observed_on: date,
        source_id: str,
    ) -> None:
        self._connection.execute(
            """
            UPDATE industry_memberships
            SET valid_to = %s
            WHERE security_id = %s AND taxonomy = %s AND valid_to IS NULL
              AND valid_from < %s
            """,
            (
                observed_on,
                security_id,
                taxonomy,
                observed_on,
            ),
        )
        result = self._connection.execute(
            """
            INSERT INTO industry_memberships (
                security_id, taxonomy, industry_name, industry_code,
                valid_from, valid_to, source_id
            )
            VALUES (%s, %s, %s, %s, %s, NULL, %s)
            ON CONFLICT (security_id, taxonomy, valid_from) DO UPDATE SET
                industry_membership_id = industry_memberships.industry_membership_id
            WHERE industry_memberships.industry_code IS NOT DISTINCT FROM
                  EXCLUDED.industry_code
              AND industry_memberships.industry_name = EXCLUDED.industry_name
              AND industry_memberships.valid_to IS NULL
              AND industry_memberships.source_id = EXCLUDED.source_id
            RETURNING industry_membership_id
            """,
            (
                security_id,
                taxonomy,
                industry_name,
                industry_code,
                observed_on,
                source_id,
            ),
        )
        self._require_immutable_write(
            result,
            "industry correction conflicts on the same effective date",
        )

    def _persist_universe(
        self,
        batch: BackfillBatch,
        payload: UniverseMembershipPayload,
        dataset_version_id: str,
    ) -> None:
        names = {"000300": "沪深 300", "000905": "中证 500"}
        definition_id = f"csi:{payload.benchmark_code}"
        checkpoint_hash = hashlib.sha256(
            batch.work_unit.checkpoint_key.encode("utf-8")
        ).hexdigest()[:20]
        universe_version_id = (
            f"universe:{payload.benchmark_code}:{dataset_version_id}:{checkpoint_hash}"
        )
        source_ids = tuple(sorted({row.source_id for row in payload.rows}))
        if not source_ids:
            raise CanonicalSinkError("universe version requires at least one source_id")
        # This is the first stable system-observation time carried by the batch.
        # It does not qualify as a historical available_at, which remains NULL.
        system_as_of = batch.metadata.retrieved_at
        definition_result = self._connection.execute(
            """
            INSERT INTO universe_definitions (
                definition_id, name, ruleset_version, benchmark_id
            ) VALUES (%s, %s, 'provider_snapshot_v1', %s)
            ON CONFLICT (definition_id) DO UPDATE SET
                definition_id = universe_definitions.definition_id
            WHERE universe_definitions.name = EXCLUDED.name
              AND universe_definitions.ruleset_version = EXCLUDED.ruleset_version
              AND universe_definitions.benchmark_id = EXCLUDED.benchmark_id
            RETURNING definition_id
            """,
            (definition_id, names[payload.benchmark_code], payload.benchmark_code),
        )
        self._require_immutable_write(
            definition_result,
            "universe definition identifier conflicts with different semantics",
        )
        version_result = self._connection.execute(
            """
            INSERT INTO universe_versions (
                universe_version_id, definition_id, dataset_version_id, created_at,
                trust_state, provider_id, source_ids, retrieved_at, system_as_of,
                available_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (universe_version_id) DO UPDATE SET
                universe_version_id = universe_versions.universe_version_id
            WHERE universe_versions.definition_id = EXCLUDED.definition_id
              AND universe_versions.dataset_version_id = EXCLUDED.dataset_version_id
              AND universe_versions.created_at = EXCLUDED.created_at
              AND universe_versions.trust_state = EXCLUDED.trust_state
              AND universe_versions.provider_id = EXCLUDED.provider_id
              AND universe_versions.source_ids = EXCLUDED.source_ids
              AND universe_versions.retrieved_at = EXCLUDED.retrieved_at
              AND universe_versions.system_as_of = EXCLUDED.system_as_of
              AND universe_versions.available_at IS NOT DISTINCT FROM EXCLUDED.available_at
            RETURNING universe_version_id
            """,
            (
                universe_version_id,
                definition_id,
                dataset_version_id,
                system_as_of,
                batch.trust_state.value,
                batch.metadata.provider_id,
                _json_parameter(list(source_ids)),
                batch.metadata.retrieved_at,
                system_as_of,
                None,
            ),
        )
        self._require_immutable_write(
            version_result,
            "universe version identifier conflicts with different lineage",
        )
        for row in payload.rows:
            listing_id = self._resolve_universe_listing(row.code, row.valid_from)
            membership_result = self._connection.execute(
                """
                INSERT INTO universe_memberships (
                    universe_version_id, listing_id, valid_from, valid_to,
                    research_eligible, tradable_eligible, inclusion_reasons,
                    exclusion_reasons, benchmark_member, source_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (universe_version_id, listing_id, valid_from) DO UPDATE SET
                    universe_membership_id = universe_memberships.universe_membership_id
                WHERE universe_memberships.valid_to = EXCLUDED.valid_to
                  AND universe_memberships.research_eligible = EXCLUDED.research_eligible
                  AND universe_memberships.tradable_eligible = EXCLUDED.tradable_eligible
                  AND universe_memberships.inclusion_reasons = EXCLUDED.inclusion_reasons
                  AND universe_memberships.exclusion_reasons = EXCLUDED.exclusion_reasons
                  AND universe_memberships.benchmark_member = EXCLUDED.benchmark_member
                  AND universe_memberships.source_id = EXCLUDED.source_id
                RETURNING universe_membership_id
                """,
                (
                    universe_version_id,
                    listing_id,
                    row.valid_from,
                    row.valid_to,
                    True,
                    False,
                    _json_parameter([f"benchmark_member:{payload.benchmark_code}"]),
                    _json_parameter(["tradability_not_evaluated"]),
                    True,
                    row.source_id,
                ),
            )
            self._require_immutable_write(
                membership_result,
                "universe membership conflicts on the same effective date",
            )

    def _resolve_universe_listing(self, code: str, as_of: date) -> str:
        try:
            return self._listing_resolver(code, as_of)
        except CanonicalSinkError:
            exchange = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}[code[:2]]
            _company_id, _security_id, listing_id = self._identity_ids(exchange, code)
            rows = self._connection.execute(
                """
                SELECT listing_id
                FROM listings
                WHERE listing_id = %s
                  AND listed_on <= %s
                  AND (delisted_on IS NULL OR %s <= delisted_on)
                """,
                (listing_id, as_of, as_of),
            ).fetchall()
            if len(rows) != 1:
                raise CanonicalSinkError(
                    "historical universe code has no compatible current identity: "
                    f"code={code}, as_of={as_of}"
                )
            return str(rows[0][0])

    @staticmethod
    def _identity_ids(exchange: str, code: str) -> tuple[str, str, str]:
        digits = code.split(".", 1)[1]
        key = f"{exchange}:{digits}"
        return (
            f"company:cn:{key}",
            f"security:cn:{key}:a-share",
            f"listing:{key}",
        )

    @staticmethod
    def _require_immutable_write(result: QueryResult, message: str) -> None:
        if result.fetchone() is None:
            raise CanonicalSinkError(message)

    @staticmethod
    def _universe_version_from_row(
        row: tuple[object, ...],
    ) -> CanonicalUniverseVersion:
        raw_source_ids = row[6]
        if isinstance(raw_source_ids, str):
            raw_source_ids = json.loads(raw_source_ids)
        if not isinstance(raw_source_ids, (list, tuple)):
            raise CanonicalSinkError("universe source_ids must be a JSON array")
        source_ids = tuple(str(value) for value in raw_source_ids)
        if not source_ids or any(not value.strip() for value in source_ids):
            raise CanonicalSinkError("universe source_ids must not be empty")
        trust_state = DataTrustState(str(row[4]))
        available_at = cast(datetime | None, row[9])
        if trust_state is DataTrustState.PIT_VERIFIED and available_at is None:
            raise CanonicalSinkError("pit_verified universe requires available_at")
        if trust_state is not DataTrustState.PIT_VERIFIED and available_at is not None:
            raise CanonicalSinkError(
                "non-PIT universe must not carry an available_at qualification"
            )
        return CanonicalUniverseVersion(
            universe_version_id=str(row[0]),
            definition_id=str(row[1]),
            dataset_version_id=str(row[2]),
            created_at=cast(datetime, row[3]),
            trust_state=trust_state,
            provider_id=str(row[5]),
            source_ids=source_ids,
            retrieved_at=cast(datetime, row[7]),
            system_as_of=cast(datetime, row[8]),
            available_at=available_at,
        )
