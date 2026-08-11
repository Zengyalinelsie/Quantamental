import unittest
from datetime import date

from a_share_platform.adapters.postgres.identity import (
    IdentityAliasConflict,
    PostgresIdentityAliasRepository,
)
from a_share_platform.adapters.sinks.canonical_backfill import (
    CanonicalSinkError,
    PostgresListingResolver,
)
from a_share_platform.domain.security_master import (
    IdentifierKind,
    OfficialIdentifierAlias,
    ProviderIdentifierCorrection,
)


class FakeResult:
    def __init__(self, rows: tuple[tuple[object, ...], ...] = ()) -> None:
        self.rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class ResolverConnection:
    def __init__(
        self,
        *,
        effective_official: tuple[tuple[object, ...], ...] = (),
        known_official: tuple[tuple[object, ...], ...] = (),
        effective_correction: tuple[tuple[object, ...], ...] = (),
        known_correction: tuple[tuple[object, ...], ...] = (),
        identifier_history: tuple[tuple[object, ...], ...] = (),
    ) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.effective_official = effective_official
        self.known_official = known_official
        self.effective_correction = effective_correction
        self.known_correction = known_correction
        self.identifier_history = identifier_history

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "FROM official_identifier_aliases" in query:
            if "aliases.valid_from <=" in query:
                return FakeResult(self.effective_official)
            return FakeResult(self.known_official)
        if "FROM provider_identifier_corrections" in query:
            if "corrections.valid_from <=" in query:
                return FakeResult(self.effective_correction)
            return FakeResult(self.known_correction)
        if "FROM identifier_history AS identifiers" in query:
            return FakeResult(self.identifier_history)
        return FakeResult()


class WriteConnection:
    def __init__(
        self,
        *,
        inserted: bool = True,
        exact_existing: bool = False,
    ) -> None:
        self.inserted = inserted
        self.exact_existing = exact_existing
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "INSERT INTO" in query:
            return FakeResult(((1,),) if self.inserted else ())
        if "SELECT" in query:
            return FakeResult(((1,),) if self.exact_existing else ())
        return FakeResult()


class PostgresIdentityTest(unittest.TestCase):
    def test_global_resolver_prefers_effective_official_alias(self) -> None:
        connection = ResolverConnection(
            effective_official=(("listing:avic-cac:xshe",),),
            identifier_history=(("listing:wrong",),),
        )

        listing_id = PostgresListingResolver(connection)(
            "SZ.300114", date(2025, 2, 14)
        )

        self.assertEqual(listing_id, "listing:avic-cac:xshe")
        sql = "\n".join(query for query, _params in connection.calls)
        self.assertNotIn("provider_identifier_corrections", sql)
        self.assertNotIn("identifier_history", sql)

    def test_global_resolver_rejects_known_alias_outside_official_interval(self) -> None:
        connection = ResolverConnection(
            known_official=(("listing:avic-cac:xshe",),),
            identifier_history=(("listing:wrong",),),
        )

        with self.assertRaisesRegex(CanonicalSinkError, "not effective"):
            PostgresListingResolver(connection)("SZ.302132", date(2025, 2, 14))

        sql = "\n".join(query for query, _params in connection.calls)
        self.assertNotIn("identifier_history", sql)

    def test_global_resolver_falls_back_to_identifier_history_for_non_alias(self) -> None:
        connection = ResolverConnection(
            identifier_history=(("listing:moutai:xshg",),)
        )

        listing_id = PostgresListingResolver(connection)(
            "SH.600519", date(2024, 12, 31)
        )

        self.assertEqual(listing_id, "listing:moutai:xshg")

    def test_provider_correction_requires_explicit_provider_id(self) -> None:
        connection = ResolverConnection(
            effective_correction=(("listing:avic-cac:xshe",),),
            identifier_history=(("listing:wrong",),),
        )
        resolver = PostgresListingResolver(connection)

        listing_id = resolver.resolve_for_provider(
            provider_id="baostock_sdk",
            code="SZ.300114",
            as_of=date(2025, 2, 14),
        )

        self.assertEqual(listing_id, "listing:avic-cac:xshe")
        correction_query, correction_params = connection.calls[0]
        self.assertIn("provider_identifier_corrections", correction_query)
        self.assertEqual(correction_params[0], "baostock_sdk")
        with self.assertRaisesRegex(ValueError, "provider_id"):
            resolver.resolve_for_provider(
                provider_id="",
                code="SZ.300114",
                as_of=date(2025, 2, 14),
            )

    def test_ambiguous_official_alias_fails_closed(self) -> None:
        connection = ResolverConnection(
            effective_official=(("listing:one",), ("listing:two",)),
        )

        with self.assertRaisesRegex(CanonicalSinkError, "official alias"):
            PostgresListingResolver(connection)("SZ.300114", date(2025, 2, 14))

    def test_repository_keeps_official_evidence_and_provider_scope_separate(self) -> None:
        connection = WriteConnection()
        repository = PostgresIdentityAliasRepository(connection)
        official = OfficialIdentifierAlias(
            listing_id="listing:avic-cac:xshe",
            kind=IdentifierKind.CODE,
            value="300114",
            valid_from=date(2010, 8, 27),
            valid_to=date(2025, 2, 17),
            source_id="cninfo:announcement:1222544408",
            evidence_url=(
                "https://static.cninfo.com.cn/finalpage/2025-02-15/"
                "1222544408.PDF"
            ),
            published_on=date(2025, 2, 14),
        )
        correction = ProviderIdentifierCorrection(
            provider_id="baostock_sdk",
            listing_id="listing:avic-cac:xshe",
            kind=IdentifierKind.CODE,
            observed_value="300114",
            valid_from=date(2010, 8, 27),
            valid_to=date(2025, 2, 17),
            source_id="operator-review:baostock:300114",
            reason="provider historical code correction",
        )

        repository.register_official_alias(official)
        repository.register_provider_correction(correction)

        self.assertIn("official_identifier_aliases", connection.calls[0][0])
        self.assertIn("ON CONFLICT DO NOTHING", connection.calls[0][0])
        self.assertNotIn("DO UPDATE", connection.calls[0][0])
        self.assertNotIn("baostock_sdk", connection.calls[0][1])
        self.assertIn("provider_identifier_corrections", connection.calls[1][0])
        self.assertIn("ON CONFLICT DO NOTHING", connection.calls[1][0])
        self.assertNotIn("DO UPDATE", connection.calls[1][0])
        self.assertEqual(connection.calls[1][1][0], "baostock_sdk")

    def test_repository_treats_an_exact_existing_official_alias_as_idempotent(self) -> None:
        connection = WriteConnection(inserted=False, exact_existing=True)
        repository = PostgresIdentityAliasRepository(connection)
        value = OfficialIdentifierAlias(
            listing_id="listing:avic-cac:xshe",
            kind=IdentifierKind.CODE,
            value="302132",
            valid_from=date(2025, 2, 17),
            valid_to=None,
            source_id="cninfo:announcement:1222544408",
            evidence_url=(
                "https://static.cninfo.com.cn/finalpage/2025-02-15/"
                "1222544408.PDF"
            ),
            published_on=date(2025, 2, 14),
        )

        repository.register_official_alias(value)

        self.assertEqual(len(connection.calls), 2)
        insert_query, insert_params = connection.calls[0]
        select_query, select_params = connection.calls[1]
        self.assertIn("ON CONFLICT DO NOTHING", insert_query)
        self.assertNotIn("DO UPDATE", insert_query)
        self.assertIn("FROM official_identifier_aliases", select_query)
        self.assertEqual(select_params, insert_params)

    def test_repository_rejects_conflicting_same_boundary_write(self) -> None:
        repository = PostgresIdentityAliasRepository(
            WriteConnection(inserted=False, exact_existing=False)
        )
        value = OfficialIdentifierAlias(
            listing_id="listing:avic-cac:xshe",
            kind=IdentifierKind.CODE,
            value="302132",
            valid_from=date(2025, 2, 17),
            valid_to=None,
            source_id="cninfo:announcement:1222544408",
            evidence_url=(
                "https://static.cninfo.com.cn/finalpage/2025-02-15/"
                "1222544408.PDF"
            ),
            published_on=date(2025, 2, 14),
        )

        with self.assertRaisesRegex(IdentityAliasConflict, "official alias conflicts"):
            repository.register_official_alias(value)

    def test_repository_rejects_conflicting_provider_correction_semantics(self) -> None:
        repository = PostgresIdentityAliasRepository(
            WriteConnection(inserted=False, exact_existing=False)
        )
        value = ProviderIdentifierCorrection(
            provider_id="baostock_sdk",
            listing_id="listing:avic-cac:xshe",
            kind=IdentifierKind.CODE,
            observed_value="300114",
            valid_from=date(2010, 8, 27),
            valid_to=date(2025, 2, 17),
            source_id="operator-review:baostock:300114",
            reason="provider historical code correction",
        )

        with self.assertRaisesRegex(IdentityAliasConflict, "provider correction conflicts"):
            repository.register_provider_correction(value)


if __name__ == "__main__":
    unittest.main()
