import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from a_share_platform.adapters.postgres.market_structure import (
    PostgresCurrentKnownListingResolver,
    PostgresMarketStructureObservationSink,
)
from a_share_platform.adapters.providers.backfill_payloads import (
    CorporateActionPayload,
    ShareCapitalPayload,
    StagedCorporateActionObservation,
    StagedShareCapitalObservation,
)
from a_share_platform.adapters.sinks.canonical_backfill import ListingResolution
from a_share_platform.adapters.sinks.routing import DomainRoutingBackfillSink
from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillDataDomain,
    BackfillWorkUnit,
    DatasetQualityStatus,
    ProviderRetrievalMetadata,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import Exchange

NOW = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def __init__(self, row: tuple[object, ...] | None = (1,)) -> None:
        self._row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class FakeConnection:
    def __init__(self, *, returned_row: tuple[object, ...] | None = (1,)) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.returned_row = returned_row

    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> FakeResult:
        self.calls.append((query, params))
        return FakeResult(self.returned_row)


class SequencedConnection(FakeConnection):
    def __init__(self, rows: list[list[tuple[object, ...]]]) -> None:
        super().__init__()
        self.rows = iter(rows)

    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> FakeResult:
        self.calls.append((query, params))
        selected = next(self.rows)
        result = FakeResult()
        result.fetchall = lambda: selected  # type: ignore[method-assign]
        return result


def batch(domain: BackfillDataDomain, payload: object) -> BackfillBatch:
    unit = BackfillWorkUnit(
        plan_id=f"private:akshare:{domain.value}:v1",
        checkpoint_key=f"{domain.value}:symbols-explicit:XSHE:2018-01-01:2018-12-31",
        scope_id="symbols:explicit",
        domain=domain,
        market="XSHE",
        start_date=date(2018, 1, 1),
        end_date=date(2018, 12, 31),
    )
    return BackfillBatch(
        work_unit=unit,
        metadata=ProviderRetrievalMetadata(
            provider_id="akshare",
            retrieved_at=NOW,
            cutoff_date=unit.end_date,
            adjustment_mode="not_applicable",
            units=(("value", "provider_defined"),),
            warnings=("normalized_current only",),
        ),
        row_count=len(payload.rows),  # type: ignore[attr-defined]
        rejected_rows=0,
        content_hash="sha256:" + "1" * 64,
        expected_rows=None,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        quality_status=DatasetQualityStatus.PASSED,
        issue_counts=(),
        warnings=(),
        payload=payload,
    )


class PostgresMarketStructureObservationSinkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()
        self.resolutions: list[tuple[str, date]] = []

    def resolver(self, code: str, as_of: date) -> ListingResolution:
        self.resolutions.append((code, as_of))
        return ListingResolution(
            listing_id="listing:stable:000858",
            warnings=("current-known identifier used",),
        )

    def test_share_capital_observation_preserves_dates_lineage_and_missing_free_float(self) -> None:
        payload = ShareCapitalPayload(
            (
                StagedShareCapitalObservation(
                    code="SZ.000858",
                    exchange=Exchange.XSHE,
                    effective_on=date(2018, 5, 10),
                    announced_on=date(2018, 5, 11),
                    total_shares=Decimal(3881608005),
                    circulating_shares=Decimal(3800000000),
                    restricted_shares=Decimal(81608005),
                    free_float_shares=None,
                    provider_record_id="cninfo:share-change:000858:2018-05-10",
                    source_id="akshare.stock_share_change_cninfo",
                ),
            )
        )
        sink = PostgresMarketStructureObservationSink(
            connection=self.connection,
            listing_resolver=self.resolver,
        )

        warnings = sink.persist(batch(BackfillDataDomain.SHARE_CAPITAL, payload), dataset_version_id="dataset:p2:share:v1")

        self.assertEqual(self.resolutions, [("SZ.000858", date(2018, 5, 10))])
        query, params = self.connection.calls[0]
        self.assertIn("INSERT INTO share_capital_observations", query)
        self.assertIn("dataset:p2:share:v1", params)
        self.assertIn("normalized_current", params)
        self.assertIn(None, params)
        self.assertEqual(warnings, ("current-known identifier used",))

    def test_corporate_action_observation_keeps_bonus_and_capitalization_separate(self) -> None:
        payload = CorporateActionPayload(
            (
                StagedCorporateActionObservation(
                    code="SZ.000858",
                    exchange=Exchange.XSHE,
                    announced_on=date(2018, 6, 15),
                    record_date=date(2018, 6, 20),
                    ex_date=date(2018, 6, 21),
                    cash_per_share=Decimal("0.467"),
                    bonus_shares_per_share=Decimal("0.1"),
                    capitalization_shares_per_share=Decimal("0.2"),
                    rights_shares_per_share=None,
                    rights_subscription_price=None,
                    currency="CNY",
                    provider_record_id="cninfo:dividend:000858:2017",
                    source_id="akshare.stock_dividend_cninfo",
                ),
            )
        )
        sink = PostgresMarketStructureObservationSink(
            connection=self.connection,
            listing_resolver=self.resolver,
        )

        sink.persist(batch(BackfillDataDomain.CORPORATE_ACTION, payload), dataset_version_id="dataset:p2:action:v1")

        query, params = self.connection.calls[0]
        self.assertIn("INSERT INTO corporate_action_observations", query)
        self.assertIn(Decimal("0.1"), params)
        self.assertIn(Decimal("0.2"), params)

    def test_same_observation_id_with_different_content_fails_closed(self) -> None:
        connection = FakeConnection(returned_row=None)
        payload = ShareCapitalPayload(
            (
                StagedShareCapitalObservation(
                    code="SZ.000858",
                    exchange=Exchange.XSHE,
                    effective_on=date(2018, 5, 10),
                    announced_on=None,
                    total_shares=Decimal(100),
                    circulating_shares=None,
                    restricted_shares=None,
                    free_float_shares=None,
                    provider_record_id="cninfo:share-change:collision",
                    source_id="akshare.stock_share_change_cninfo",
                ),
            )
        )
        sink = PostgresMarketStructureObservationSink(
            connection=connection,
            listing_resolver=self.resolver,
        )

        with self.assertRaisesRegex(RuntimeError, "conflicts"):
            sink.persist(batch(BackfillDataDomain.SHARE_CAPITAL, payload), dataset_version_id="dataset:p2:share:v1")

    def test_migration_uses_append_only_observation_tables_without_available_at(self) -> None:
        migration = (ROOT / "migrations" / "0020_market_structure_observations.sql").read_text()

        self.assertIn("CREATE TABLE share_capital_observations", migration)
        self.assertIn("CREATE TABLE corporate_action_observations", migration)
        self.assertIn("bonus_shares_per_share", migration)
        self.assertIn("capitalization_shares_per_share", migration)
        self.assertIn("trust_state = 'normalized_current'", migration)
        self.assertNotIn("available_at", migration)
        self.assertGreaterEqual(migration.count("BEFORE UPDATE OR DELETE"), 2)

    def test_domain_routing_sends_market_structure_to_observation_sink(self) -> None:
        calls: list[tuple[str, BackfillDataDomain, str]] = []

        class Sink:
            def __init__(self, name: str) -> None:
                self.name = name

            def persist(self, value: BackfillBatch, *, dataset_version_id: str):  # type: ignore[no-untyped-def]
                calls.append((self.name, value.work_unit.domain, dataset_version_id))
                return (self.name,)

        payload = ShareCapitalPayload(
            (
                StagedShareCapitalObservation(
                    code="SZ.000858",
                    exchange=Exchange.XSHE,
                    effective_on=date(2018, 5, 10),
                    announced_on=None,
                    total_shares=Decimal(100),
                    circulating_shares=None,
                    restricted_shares=None,
                    free_float_shares=None,
                    provider_record_id="cninfo:share-change:routed",
                    source_id="akshare.stock_share_change_cninfo",
                ),
            )
        )
        sink = DomainRoutingBackfillSink(
            default_sink=Sink("canonical"),
            routes={BackfillDataDomain.SHARE_CAPITAL: Sink("observation")},
        )

        warnings = sink.persist(
            batch(BackfillDataDomain.SHARE_CAPITAL, payload),
            dataset_version_id="dataset:p2:routed:v1",
        )

        self.assertEqual(
            calls,
            [("observation", BackfillDataDomain.SHARE_CAPITAL, "dataset:p2:routed:v1")],
        )
        self.assertEqual(warnings, ("observation",))


class PostgresCurrentKnownListingResolverTest(unittest.TestCase):
    def test_effective_identifier_wins_without_current_warning(self) -> None:
        connection = SequencedConnection([[('listing:stable:000858',)]])
        resolver = PostgresCurrentKnownListingResolver(connection)

        result = resolver("SZ.000858", date(2018, 5, 10))

        self.assertEqual(result.listing_id, "listing:stable:000858")
        self.assertEqual(result.warnings, ())
        self.assertEqual(len(connection.calls), 1)

    def test_unique_current_known_identifier_can_map_normalized_current_history(self) -> None:
        connection = SequencedConnection(
            [[], [('listing:stable:000858',)]]
        )
        resolver = PostgresCurrentKnownListingResolver(connection)

        result = resolver("SZ.000858", date(2018, 5, 10))

        self.assertEqual(result.listing_id, "listing:stable:000858")
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("current-known", result.warnings[0])
        self.assertNotIn("listing:XSHE:000858", str(connection.calls))

    def test_code_reuse_or_missing_identity_fails_closed(self) -> None:
        cases = (
            [[ ], []],
            [[], [('listing:a',), ('listing:b',)]],
        )
        for rows in cases:
            with self.subTest(rows=rows):
                resolver = PostgresCurrentKnownListingResolver(SequencedConnection(rows))
                with self.assertRaisesRegex(RuntimeError, "unique"):
                    resolver("SH.600079", date(2018, 5, 10))


if __name__ == "__main__":
    unittest.main()
