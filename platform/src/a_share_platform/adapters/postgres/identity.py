"""PostgreSQL persistence for official aliases and provider-local corrections."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.security_master import (
    OfficialIdentifierAlias,
    ProviderIdentifierCorrection,
)


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class IdentityAliasConflict(RuntimeError):
    """Raised when an immutable alias boundary conflicts with stored identity."""


class PostgresIdentityAliasRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def register_official_alias(self, value: OfficialIdentifierAlias) -> None:
        params = (
            value.listing_id,
            value.kind.value,
            value.value,
            value.valid_from,
            value.valid_to,
            value.source_id,
            value.evidence_url,
            value.published_on,
        )
        result = self._connection.execute(
            """
            INSERT INTO canonical.official_identifier_aliases (
                listing_id, kind, value, valid_from, valid_to, source_id,
                evidence_url, published_on
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING official_identifier_alias_id
            """,
            params,
        )
        if result.fetchone() is not None:
            return
        existing = self._connection.execute(
            """
            SELECT official_identifier_alias_id
            FROM canonical.official_identifier_aliases
            WHERE listing_id = %s
              AND kind = %s
              AND value = %s
              AND valid_from = %s
              AND valid_to IS NOT DISTINCT FROM %s
              AND source_id = %s
              AND evidence_url = %s
              AND published_on = %s
            """,
            params,
        ).fetchone()
        if existing is not None:
            return
        raise IdentityAliasConflict(
            "official alias conflicts on the same effective boundary"
        )

    def register_provider_correction(
        self,
        value: ProviderIdentifierCorrection,
    ) -> None:
        params = (
            value.provider_id,
            value.listing_id,
            value.kind.value,
            value.observed_value,
            value.valid_from,
            value.valid_to,
            value.source_id,
            value.reason,
        )
        result = self._connection.execute(
            """
            INSERT INTO canonical.provider_identifier_corrections (
                provider_id, listing_id, kind, observed_value, valid_from,
                valid_to, source_id, reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            RETURNING provider_identifier_correction_id
            """,
            params,
        )
        if result.fetchone() is not None:
            return
        existing = self._connection.execute(
            """
            SELECT provider_identifier_correction_id
            FROM canonical.provider_identifier_corrections
            WHERE provider_id = %s
              AND listing_id = %s
              AND kind = %s
              AND observed_value = %s
              AND valid_from = %s
              AND valid_to IS NOT DISTINCT FROM %s
              AND source_id = %s
              AND reason = %s
            """,
            params,
        ).fetchone()
        if existing is not None:
            return
        raise IdentityAliasConflict(
            "provider correction conflicts on the same effective boundary"
        )
