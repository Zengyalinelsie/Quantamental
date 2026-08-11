"""Append-only PostgreSQL sink for normalized-current market-structure observations."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date
from typing import Protocol

from a_share_platform.adapters.postgres.schema_layers import qualified_table
from a_share_platform.adapters.providers.backfill_payloads import (
    CorporateActionPayload,
    ShareCapitalPayload,
    StagedCorporateActionObservation,
    StagedShareCapitalObservation,
)
from a_share_platform.adapters.sinks.canonical_backfill import (
    CURRENT_KNOWN_IDENTITY_MAPPING_WARNING,
    ListingResolution,
)
from a_share_platform.domain.backfill import BackfillBatch, BackfillDataDomain
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


class PostgresCurrentKnownListingResolver:
    """Resolve by stored identifiers only; never derive identity from a request code."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def __call__(self, code: str, as_of: date) -> ListingResolution:
        if len(code) != 9 or code[2] != "." or not code[3:].isdigit():
            raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000")
        try:
            exchange = {"SH": "XSHG", "SZ": "XSHE", "BJ": "XBSE"}[code[:2]]
        except KeyError as error:
            raise ValueError("code must use SH.000000, SZ.000000, or BJ.000000") from error
        params = (code.split(".", 1)[1], as_of, as_of, exchange, as_of, as_of)
        effective = self._connection.execute(
            """
            SELECT DISTINCT identifiers.listing_id
            FROM canonical.identifier_history AS identifiers
            JOIN canonical.listings ON listings.listing_id = identifiers.listing_id
            WHERE identifiers.kind = 'code'
              AND identifiers.value = %s
              AND identifiers.valid_from <= %s
              AND (identifiers.valid_to IS NULL OR %s < identifiers.valid_to)
              AND listings.exchange = %s
              AND listings.listed_on <= %s
              AND (listings.delisted_on IS NULL OR %s <= listings.delisted_on)
            ORDER BY identifiers.listing_id
            """,
            params,
        ).fetchall()
        if len(effective) > 1:
            raise RuntimeError(
                f"effective identifier does not resolve to one unique listing: code={code}"
            )
        if effective:
            return ListingResolution(str(effective[0][0]))

        current_known = self._connection.execute(
            """
            SELECT DISTINCT identifiers.listing_id
            FROM canonical.identifier_history AS identifiers
            JOIN canonical.listings ON listings.listing_id = identifiers.listing_id
            WHERE identifiers.kind = 'code'
              AND identifiers.value = %s
              AND listings.exchange = %s
              AND listings.listed_on <= %s
              AND (listings.delisted_on IS NULL OR %s <= listings.delisted_on)
            ORDER BY identifiers.listing_id
            """,
            (code.split(".", 1)[1], exchange, as_of, as_of),
        ).fetchall()
        if len(current_known) != 1:
            raise RuntimeError(
                "current-known identifier requires one unique compatible listing: "
                f"code={code}, as_of={as_of}; got {len(current_known)}"
            )
        return ListingResolution(
            str(current_known[0][0]),
            warnings=(CURRENT_KNOWN_IDENTITY_MAPPING_WARNING,),
        )


class PostgresMarketStructureObservationSink:
    """Persist provider observations without fabricating historical availability."""

    def __init__(
        self,
        *,
        connection: Connection,
        listing_resolver: Callable[[str, date], ListingResolution],
    ) -> None:
        self._connection = connection
        self._listing_resolver = listing_resolver

    def persist(
        self,
        batch: BackfillBatch,
        *,
        dataset_version_id: str,
    ) -> tuple[str, ...]:
        if not dataset_version_id.strip():
            raise ValueError("dataset_version_id must not be empty")
        if batch.trust_state is not DataTrustState.NORMALIZED_CURRENT:
            raise RuntimeError("market-structure observation sink accepts normalized_current only")
        warnings: set[str] = set()
        if (
            batch.work_unit.domain is BackfillDataDomain.SHARE_CAPITAL
            and isinstance(batch.payload, ShareCapitalPayload)
        ):
            for share_row in batch.payload.rows:
                resolution = self._listing_resolver(
                    share_row.code,
                    share_row.effective_on,
                )
                warnings.update(resolution.warnings)
                self._insert_share_capital(
                    batch,
                    dataset_version_id,
                    resolution.listing_id,
                    share_row,
                )
            return tuple(sorted(warnings))
        if (
            batch.work_unit.domain is BackfillDataDomain.CORPORATE_ACTION
            and isinstance(batch.payload, CorporateActionPayload)
        ):
            for action_row in batch.payload.rows:
                event_date = (
                    action_row.ex_date
                    or action_row.record_date
                    or action_row.announced_on
                )
                if event_date is None:
                    raise RuntimeError(
                        "corporate action has no resolvable date: "
                        f"{action_row.provider_record_id}"
                    )
                resolution = self._listing_resolver(action_row.code, event_date)
                warnings.update(resolution.warnings)
                self._insert_corporate_action(
                    batch,
                    dataset_version_id,
                    resolution.listing_id,
                    action_row,
                )
            return tuple(sorted(warnings))
        raise RuntimeError(
            f"market-structure payload does not implement domain={batch.work_unit.domain.value}"
        )

    def _insert_share_capital(
        self,
        batch: BackfillBatch,
        dataset_version_id: str,
        listing_id: str,
        row: StagedShareCapitalObservation,
    ) -> None:
        semantic_values: tuple[object, ...] = (
            listing_id,
            batch.metadata.provider_id,
            row.provider_record_id,
            row.effective_on,
            row.announced_on,
            row.total_shares,
            row.circulating_shares,
            row.restricted_shares,
            row.free_float_shares,
            row.source_id,
            batch.metadata.retrieved_at,
            dataset_version_id,
            batch.trust_state.value,
            batch.content_hash,
        )
        observation_id = self._observation_id("share-capital", semantic_values)
        result = self._connection.execute(
            """
            INSERT INTO observation.share_capital_observations (
                observation_id, listing_id, provider_id, provider_record_id,
                effective_on, announced_on, total_shares, circulating_shares,
                restricted_shares, free_float_shares, source_id, retrieved_at,
                dataset_version_id, trust_state, batch_content_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT DO NOTHING
            RETURNING observation_id
            """,
            (observation_id, *semantic_values),
        )
        self._require_idempotent_insert(
            result,
            table="share_capital_observations",
            observation_id=observation_id,
            provider_id=batch.metadata.provider_id,
            provider_record_id=row.provider_record_id,
            dataset_version_id=dataset_version_id,
        )

    def _insert_corporate_action(
        self,
        batch: BackfillBatch,
        dataset_version_id: str,
        listing_id: str,
        row: StagedCorporateActionObservation,
    ) -> None:
        semantic_values: tuple[object, ...] = (
            listing_id,
            batch.metadata.provider_id,
            row.provider_record_id,
            row.announced_on,
            row.record_date,
            row.ex_date,
            row.cash_per_share,
            row.bonus_shares_per_share,
            row.capitalization_shares_per_share,
            row.rights_shares_per_share,
            row.rights_subscription_price,
            row.currency,
            row.source_id,
            batch.metadata.retrieved_at,
            dataset_version_id,
            batch.trust_state.value,
            batch.content_hash,
        )
        observation_id = self._observation_id("corporate-action", semantic_values)
        result = self._connection.execute(
            """
            INSERT INTO observation.corporate_action_observations (
                observation_id, listing_id, provider_id, provider_record_id,
                announced_on, record_date, ex_date, cash_per_share,
                bonus_shares_per_share, capitalization_shares_per_share,
                rights_shares_per_share, rights_subscription_price, currency,
                source_id, retrieved_at, dataset_version_id, trust_state,
                batch_content_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT DO NOTHING
            RETURNING observation_id
            """,
            (observation_id, *semantic_values),
        )
        self._require_idempotent_insert(
            result,
            table="corporate_action_observations",
            observation_id=observation_id,
            provider_id=batch.metadata.provider_id,
            provider_record_id=row.provider_record_id,
            dataset_version_id=dataset_version_id,
        )

    def _require_idempotent_insert(
        self,
        result: QueryResult,
        *,
        table: str,
        observation_id: str,
        provider_id: str,
        provider_record_id: str,
        dataset_version_id: str,
    ) -> None:
        inserted = result.fetchone()
        if inserted is not None:
            return
        if table not in {
            "share_capital_observations",
            "corporate_action_observations",
        }:
            raise AssertionError("unexpected market-structure observation table")
        qualified = qualified_table(table)
        existing = self._connection.execute(
            f"""
            SELECT observation_id
            FROM {qualified}
            WHERE provider_id = %s
              AND provider_record_id = %s
              AND dataset_version_id = %s
            """,
            (provider_id, provider_record_id, dataset_version_id),
        ).fetchone()
        if existing is None or str(existing[0]) != observation_id:
            raise RuntimeError(
                "market-structure provider record conflicts with immutable observation"
            )

    @staticmethod
    def _observation_id(prefix: str, values: tuple[object, ...]) -> str:
        encoded = "\x1f".join("<null>" if value is None else str(value) for value in values)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
        return f"observation:{prefix}:{digest}"
