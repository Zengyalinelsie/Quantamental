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
    StagedUniverseMembership,
    TradingCalendarPayload,
    UniverseMembershipPayload,
)
from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillDataDomain,
    UniverseObservationMode,
)
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


CURRENT_KNOWN_IDENTITY_MAPPING_WARNING = (
    "current-known identity mapping used for normalized_current persistence; "
    "identifier validity at the historical date is not PIT verified"
)


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
    observation_mode: UniverseObservationMode
    observed_dates: tuple[date, ...]
    unobserved_intervals: tuple[tuple[date, date], ...]


@dataclass(frozen=True)
class ListingResolution:
    listing_id: str
    warnings: tuple[str, ...] = ()


class PostgresListingResolver:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def __call__(self, code: str, as_of: date) -> str:
        exchange = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}[code[:2]]
        value = code.split(".", 1)[1]
        official_rows = self._connection.execute(
            """
            SELECT aliases.listing_id
            FROM canonical.official_identifier_aliases AS aliases
            JOIN canonical.listings ON listings.listing_id = aliases.listing_id
            WHERE aliases.kind = 'code'
              AND aliases.value = %s
              AND aliases.valid_from <= %s
              AND (aliases.valid_to IS NULL OR %s < aliases.valid_to)
              AND listings.exchange = %s
            ORDER BY aliases.listing_id
            """,
            (value, as_of, as_of, exchange),
        ).fetchall()
        if official_rows:
            return self._one_listing(
                official_rows,
                context=f"official alias for code={code}, as_of={as_of}",
            )
        known_official_rows = self._connection.execute(
            """
            SELECT aliases.listing_id
            FROM canonical.official_identifier_aliases AS aliases
            JOIN canonical.listings ON listings.listing_id = aliases.listing_id
            WHERE aliases.kind = 'code'
              AND aliases.value = %s
              AND listings.exchange = %s
            ORDER BY aliases.listing_id
            """,
            (value, exchange),
        ).fetchall()
        if known_official_rows:
            raise CanonicalSinkError(
                f"official alias exists but is not effective: code={code}, as_of={as_of}"
            )
        rows = self._connection.execute(
            """
            SELECT identifiers.listing_id
            FROM canonical.identifier_history AS identifiers
            JOIN canonical.listings ON listings.listing_id = identifiers.listing_id
            WHERE identifiers.kind = 'code'
              AND identifiers.value = %s
              AND identifiers.valid_from <= %s
              AND (identifiers.valid_to IS NULL OR %s < identifiers.valid_to)
              AND listings.exchange = %s
            ORDER BY identifiers.listing_id
            """,
            (value, as_of, as_of, exchange),
        ).fetchall()
        return self._one_listing(
            rows,
            context=f"effective listing for code={code}, as_of={as_of}",
        )

    def resolve_for_provider(
        self,
        *,
        provider_id: str,
        code: str,
        as_of: date,
    ) -> str:
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise ValueError("provider_id must not be empty")
        exchange = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}[code[:2]]
        value = code.split(".", 1)[1]
        correction_rows = self._connection.execute(
            """
            SELECT corrections.listing_id
            FROM canonical.provider_identifier_corrections AS corrections
            JOIN canonical.listings ON listings.listing_id = corrections.listing_id
            WHERE corrections.provider_id = %s
              AND corrections.kind = 'code'
              AND corrections.observed_value = %s
              AND corrections.valid_from <= %s
              AND (corrections.valid_to IS NULL OR %s < corrections.valid_to)
              AND listings.exchange = %s
            ORDER BY corrections.listing_id
            """,
            (provider_id, value, as_of, as_of, exchange),
        ).fetchall()
        if correction_rows:
            return self._one_listing(
                correction_rows,
                context=(
                    f"provider correction for provider_id={provider_id}, "
                    f"code={code}, as_of={as_of}"
                ),
            )
        known_correction_rows = self._connection.execute(
            """
            SELECT corrections.listing_id
            FROM canonical.provider_identifier_corrections AS corrections
            JOIN canonical.listings ON listings.listing_id = corrections.listing_id
            WHERE corrections.provider_id = %s
              AND corrections.kind = 'code'
              AND corrections.observed_value = %s
              AND listings.exchange = %s
            ORDER BY corrections.listing_id
            """,
            (provider_id, value, exchange),
        ).fetchall()
        if known_correction_rows:
            raise CanonicalSinkError(
                "provider correction exists but is not effective: "
                f"provider_id={provider_id}, code={code}, as_of={as_of}"
            )
        return self(code, as_of)

    @staticmethod
    def _one_listing(
        rows: list[tuple[object, ...]],
        *,
        context: str,
    ) -> str:
        if len(rows) != 1:
            raise CanonicalSinkError(f"expected one {context}; got {len(rows)}")
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
        self._postgres_listing_resolver = (
            PostgresListingResolver(connection) if listing_resolver is None else None
        )
        self._listing_resolver = listing_resolver or self._postgres_listing_resolver

    def persist(
        self,
        batch: BackfillBatch,
        *,
        dataset_version_id: str,
    ) -> tuple[str, ...]:
        if not dataset_version_id.strip():
            raise ValueError("dataset_version_id must not be empty")
        if batch.trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise CanonicalSinkError("private local sink accepts only normalized_current")
        if (
            batch.work_unit.domain is BackfillDataDomain.RAW_DAILY_BAR
            and isinstance(batch.payload, DailyObservationPayload)
        ):
            return self._persist_daily(batch, batch.payload, dataset_version_id)
        if (
            batch.work_unit.domain is BackfillDataDomain.TRADING_CALENDAR
            and isinstance(batch.payload, TradingCalendarPayload)
        ):
            self._persist_calendar(batch.payload)
            return ()
        if (
            batch.work_unit.domain is BackfillDataDomain.SECURITY_MASTER
            and isinstance(batch.payload, SecurityMasterPayload)
        ):
            self._persist_security_master(batch.payload, dataset_version_id)
            return ()
        if (
            batch.work_unit.domain is BackfillDataDomain.UNIVERSE
            and isinstance(batch.payload, UniverseMembershipPayload)
        ):
            return self._persist_universe(batch, batch.payload, dataset_version_id)
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
                   , observation_mode, observed_dates, unobserved_intervals
            FROM canonical.universe_versions
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
    ) -> tuple[str, ...]:
        bars: list[DailyBar] = []
        states: list[DailyMarketState] = []
        warnings: set[str] = set()
        for row in payload.rows:
            resolution = self._resolve_listing(
                row.code,
                row.session_date,
                trust_state=batch.trust_state,
                provider_id=batch.metadata.provider_id,
            )
            listing_id = resolution.listing_id
            warnings.update(resolution.warnings)
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
                INSERT INTO observation.daily_market_states (
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
        return tuple(sorted(warnings))

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
            INSERT INTO observation.market_data_partitions (
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
                INSERT INTO canonical.exchange_calendar_days (
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
                INSERT INTO canonical.companies (
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
                INSERT INTO canonical.securities (
                    security_id, company_id, security_class, currency
                ) VALUES (%s, %s, 'a_share', 'CNY')
                ON CONFLICT (security_id) DO NOTHING
                """,
                (security_id, company_id),
            )
            self._connection.execute(
                """
                INSERT INTO canonical.listings (
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
                    dataset_version_id=dataset_version_id,
                    observed_at=self._clock(),
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
            UPDATE canonical.identifier_history
            SET valid_to = %s
            WHERE listing_id = %s AND kind = %s AND valid_to IS NULL
              AND valid_from < %s
            """,
            (observed_on, listing_id, kind, observed_on),
        )
        result = self._connection.execute(
            """
            INSERT INTO canonical.identifier_history (
                listing_id, kind, value, valid_from, valid_to, source_id
            )
            VALUES (%s, %s, %s, %s, NULL, %s)
            ON CONFLICT (listing_id, kind, valid_from) DO UPDATE SET
                value = identifier_history.value
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
            UPDATE canonical.listing_state_periods
            SET valid_to = %s
            WHERE listing_id = %s AND valid_to IS NULL AND valid_from < %s
            """,
            (valid_from, listing_id, valid_from),
        )
        result = self._connection.execute(
            """
            INSERT INTO canonical.listing_state_periods (
                listing_id, valid_from, valid_to, state, special_treatment, source_id
            )
            VALUES (%s, %s, NULL, %s, %s, %s)
            ON CONFLICT (listing_id, valid_from) DO UPDATE SET
                state = listing_state_periods.state
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
        dataset_version_id: str,
        observed_at: datetime,
    ) -> None:
        self._connection.execute(
            """
            UPDATE canonical.industry_memberships
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
            INSERT INTO canonical.industry_memberships (
                security_id, taxonomy, industry_name, industry_code,
                valid_from, valid_to, source_id, dataset_version_id,
                trust_state, observed_at, available_at
            )
            VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s, NULL)
            ON CONFLICT (security_id, taxonomy, valid_from) DO UPDATE SET
                industry_name = industry_memberships.industry_name
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
                dataset_version_id,
                DataTrustState.NORMALIZED_CURRENT.value,
                observed_at,
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
    ) -> tuple[str, ...]:
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
        resolved_rows: list[tuple[StagedUniverseMembership, ListingResolution]] = []
        preflight_failures: list[str] = []
        for row in payload.rows:
            try:
                resolution = self._resolve_listing(
                    row.code,
                    row.valid_from,
                    trust_state=batch.trust_state,
                    provider_id=batch.metadata.provider_id,
                )
            except CanonicalSinkError as error:
                preflight_failures.append(
                    f"{row.code}@{row.valid_from.isoformat()}: {error}"
                )
                continue
            resolved_rows.append((row, resolution))
        if preflight_failures:
            raise CanonicalSinkError(
                "universe identity preflight failed: " + "; ".join(preflight_failures)
            )
        # This is the first stable system-observation time carried by the batch.
        # It does not qualify as a historical available_at, which remains NULL.
        system_as_of = batch.metadata.retrieved_at
        definition_result = self._connection.execute(
            """
            INSERT INTO canonical.universe_definitions (
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
            INSERT INTO canonical.universe_versions (
                universe_version_id, definition_id, dataset_version_id, created_at,
                trust_state, provider_id, source_ids, retrieved_at, system_as_of,
                available_at, observation_mode, observed_dates, unobserved_intervals
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
              AND universe_versions.observation_mode = EXCLUDED.observation_mode
              AND universe_versions.observed_dates = EXCLUDED.observed_dates
              AND universe_versions.unobserved_intervals = EXCLUDED.unobserved_intervals
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
                payload.observation_mode.value,
                _json_parameter(
                    [item.isoformat() for item in payload.observed_dates]
                ),
                _json_parameter(
                    [
                        {"start": lower.isoformat(), "end": upper.isoformat()}
                        for lower, upper in payload.unobserved_intervals
                    ]
                ),
            ),
        )
        self._require_immutable_write(
            version_result,
            "universe version identifier conflicts with different lineage",
        )
        warnings: set[str] = set()
        for row, resolution in resolved_rows:
            listing_id = resolution.listing_id
            warnings.update(resolution.warnings)
            membership_result = self._connection.execute(
                """
                INSERT INTO canonical.universe_memberships (
                    universe_version_id, listing_id, valid_from, valid_to,
                    research_eligible, tradable_eligible, inclusion_reasons,
                    exclusion_reasons, benchmark_member, source_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (universe_version_id, listing_id, valid_from) DO UPDATE SET
                    benchmark_member = universe_memberships.benchmark_member
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
        return tuple(sorted(warnings))

    def _resolve_listing(
        self,
        code: str,
        as_of: date,
        *,
        trust_state: DataTrustState,
        provider_id: str,
    ) -> ListingResolution:
        try:
            if self._postgres_listing_resolver is not None:
                listing_id = self._postgres_listing_resolver.resolve_for_provider(
                    provider_id=provider_id,
                    code=code,
                    as_of=as_of,
                )
            else:
                assert self._listing_resolver is not None
                listing_id = self._listing_resolver(code, as_of)
            return ListingResolution(listing_id)
        except CanonicalSinkError as strict_error:
            if trust_state is not DataTrustState.NORMALIZED_CURRENT:
                raise
            exchange = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}[code[:2]]
            _company_id, _security_id, listing_id = self._identity_ids(exchange, code)
            rows = self._connection.execute(
                """
                SELECT listing_id
                FROM canonical.listings
                WHERE listing_id = %s
                  AND exchange = %s
                  AND listed_on <= %s
                  AND (delisted_on IS NULL OR %s <= delisted_on)
                """,
                (listing_id, exchange, as_of, as_of),
            ).fetchall()
            if len(rows) != 1:
                raise CanonicalSinkError(
                    "current-known identity fallback requires one unique compatible "
                    f"current identity: code={code}, as_of={as_of}; got {len(rows)}"
                ) from strict_error
            return ListingResolution(
                listing_id=str(rows[0][0]),
                warnings=(CURRENT_KNOWN_IDENTITY_MAPPING_WARNING,),
            )

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
        observation_mode = UniverseObservationMode(str(row[10]))
        raw_observed_dates = row[11]
        if isinstance(raw_observed_dates, str):
            raw_observed_dates = json.loads(raw_observed_dates)
        if not isinstance(raw_observed_dates, (list, tuple)):
            raise CanonicalSinkError("universe observed_dates must be a JSON array")
        observed_dates = tuple(date.fromisoformat(str(item)) for item in raw_observed_dates)
        raw_unobserved = row[12]
        if isinstance(raw_unobserved, str):
            raw_unobserved = json.loads(raw_unobserved)
        if not isinstance(raw_unobserved, (list, tuple)):
            raise CanonicalSinkError(
                "universe unobserved_intervals must be a JSON array"
            )
        unobserved_intervals: list[tuple[date, date]] = []
        for raw_interval in raw_unobserved:
            if not isinstance(raw_interval, dict):
                raise CanonicalSinkError(
                    "universe unobserved interval must be a JSON object"
                )
            try:
                lower = date.fromisoformat(str(raw_interval["start"]))
                upper = date.fromisoformat(str(raw_interval["end"]))
            except (KeyError, ValueError) as error:
                raise CanonicalSinkError(
                    "universe unobserved interval has invalid boundaries"
                ) from error
            if upper <= lower:
                raise CanonicalSinkError(
                    "universe unobserved interval end must follow start"
                )
            unobserved_intervals.append((lower, upper))
        if (
            observation_mode is UniverseObservationMode.DISCRETE_MONTH_END
            and not observed_dates
        ):
            raise CanonicalSinkError(
                "discrete universe version requires observed_dates"
            )
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
            observation_mode=observation_mode,
            observed_dates=observed_dates,
            unobserved_intervals=tuple(unobserved_intervals),
        )
