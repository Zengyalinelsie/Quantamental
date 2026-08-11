import inspect
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.adapters.postgres.schema_layers import qualified_table
from a_share_platform.adapters.providers.backfill_payloads import (
    DailyObservationPayload,
    SecurityMasterPayload,
    StagedDailyObservation,
    StagedSecurityIdentity,
    StagedTradingCalendarDay,
    StagedUniverseMembership,
    TradingCalendarPayload,
    UniverseMembershipPayload,
)
from a_share_platform.adapters.sinks.canonical_backfill import (
    CanonicalBackfillSink,
    CanonicalSinkError,
)
from a_share_platform.application.backfill import (
    BackfillPlanner,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillDataDomain,
    DatasetQualityStatus,
    ProviderRetrievalMetadata,
    UniverseObservationMode,
)
from a_share_platform.domain.governance import DatasetVersion, VersionConflictError
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import (
    Board,
    Exchange,
    ListingState,
    SpecialTreatment,
)

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


class FakeResult:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[object, ...]]:
        return [] if self.row is None else [self.row]


class FakeConnection:
    def __init__(self, selected: tuple[object, ...] | None = None) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.selected = selected

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "SELECT dataset_version_id" in query:
            return FakeResult(self.selected)
        if "RETURNING" in query:
            return FakeResult((True,))
        return FakeResult()


class CurrentIdentityFallbackConnection(FakeConnection):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "RETURNING" in query:
            return FakeResult((True,))
        if "FROM canonical.identifier_history AS identifiers" in query:
            return FakeResult()
        if "FROM canonical.listings" in query and "listed_on <=" in query:
            return FakeResult(("listing:XSHG:600519",))
        return FakeResult()


class ProviderCorrectionConnection(FakeConnection):
    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if "RETURNING" in query:
            return FakeResult((True,))
        if "FROM canonical.provider_identifier_corrections" in query:
            if "corrections.valid_from <=" in query:
                return FakeResult(("listing:XSHE:302132",))
            return FakeResult()
        return FakeResult()


class FakeParquetStore:
    def __init__(self) -> None:
        self.bars: list[object] = []

    def write_bars(self, bars: object) -> tuple[Path, ...]:
        self.bars = list(bars)  # type: ignore[arg-type]
        return (Path("/research/daily_bars/part-00000.parquet"),)

    def ensure_bars(self, bars: object) -> tuple[Path, ...]:
        return self.write_bars(bars)


def plan_and_unit(domain: BackfillDataDomain):
    plan = build_private_local_backfill_plan(
        plan_id=f"private:{domain.value}:v1",
        provider_id="baostock_sdk",
        symbols=("SH.600519",),
        domains=(domain,),
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 5),
        created_at=NOW,
    )
    return plan, BackfillPlanner().work_units(plan)[0]


def batch_for(domain: BackfillDataDomain, payload: object) -> BackfillBatch:
    _plan, unit = plan_and_unit(domain)
    return BackfillBatch(
        work_unit=unit,
        metadata=ProviderRetrievalMetadata(
            provider_id="baostock_sdk",
            retrieved_at=NOW,
            cutoff_date=date(2018, 1, 2),
            adjustment_mode="unadjusted",
            units=(("volume", "shares"),),
            warnings=("normalized_current only",),
        ),
        row_count=1,
        rejected_rows=0,
        content_hash=HASH,
        expected_rows=None,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        quality_status=DatasetQualityStatus.PASSED,
        issue_counts=(),
        warnings=(),
        payload=payload,
    )


class CanonicalBackfillSinkTest(unittest.TestCase):
    def test_registers_dataset_before_business_foreign_keys_and_detects_conflict(self) -> None:
        value = DatasetVersion("dataset:test:v1", HASH, NOW, "p2-backfill-v1")
        metadata = {
            "manifest": {
                "plan_id": "private:universe:v1",
                "provider_id": "a_share_identity_universe",
            }
        }
        connection = FakeConnection(
            (
                value.dataset_version_id,
                value.content_hash,
                value.created_at,
                value.schema_version,
                metadata,
            )
        )
        repository = PostgresDatasetVersionRepository(connection)

        self.assertEqual(repository.register_dataset(value, metadata=metadata), value)
        self.assertEqual(repository.dataset_metadata(value.dataset_version_id), metadata)
        self.assertIn("INSERT INTO governance.dataset_versions", connection.calls[0][0])
        self.assertIn("metadata", connection.calls[0][0])
        self.assertIn("SELECT dataset_version_id", connection.calls[1][0])

        conflict_connection = FakeConnection(
            (
                value.dataset_version_id,
                "sha256:" + "b" * 64,
                value.created_at,
                value.schema_version,
                metadata,
            )
        )
        with self.assertRaises(VersionConflictError):
            PostgresDatasetVersionRepository(conflict_connection).register_dataset(
                value, metadata=metadata
            )

        metadata_conflict = FakeConnection(
            (
                value.dataset_version_id,
                value.content_hash,
                value.created_at,
                value.schema_version,
                {"manifest": {"provider_id": "different"}},
            )
        )
        with self.assertRaisesRegex(VersionConflictError, "metadata"):
            PostgresDatasetVersionRepository(metadata_conflict).register_dataset(
                value, metadata=metadata
            )

    def test_persists_normalized_bars_states_and_partition_manifest(self) -> None:
        connection = FakeConnection()
        parquet = FakeParquetStore()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=parquet,  # type: ignore[arg-type]
            listing_resolver=lambda code, as_of: f"listing:{code}:{as_of.isoformat()}",
            clock=lambda: NOW,
        )
        payload = DailyObservationPayload(
            rows=(
                StagedDailyObservation(
                    code="SH.600519",
                    exchange=Exchange.XSHG,
                    session_date=date(2018, 1, 2),
                    currency="CNY",
                    open=Decimal(700),
                    high=Decimal(710),
                    low=Decimal(699),
                    close=Decimal(705),
                    previous_close=Decimal("697.49"),
                    volume_shares=4_961_248,
                    amount=Decimal(3497193408),
                    is_trading=True,
                    special_treatment=SpecialTreatment.NONE,
                    source_id="baostock_sdk",
                ),
            )
        )

        sink.persist(batch_for(BackfillDataDomain.RAW_DAILY_BAR, payload), dataset_version_id="dataset:test:v1")

        self.assertEqual(len(parquet.bars), 1)
        self.assertEqual(parquet.bars[0].trust_state, DataTrustState.NORMALIZED_CURRENT)
        sql = "\n".join(query for query, _params in connection.calls)
        self.assertIn("INSERT INTO observation.daily_market_states", sql)
        self.assertIn("INSERT INTO observation.market_data_partitions", sql)

    def test_normalized_current_bars_use_unique_current_known_listing_with_warning(self) -> None:
        connection = CurrentIdentityFallbackConnection()
        parquet = FakeParquetStore()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=parquet,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = DailyObservationPayload(
            rows=(
                StagedDailyObservation(
                    code="SH.600519",
                    exchange=Exchange.XSHG,
                    session_date=date(2018, 1, 2),
                    currency="CNY",
                    open=Decimal(700),
                    high=Decimal(710),
                    low=Decimal(699),
                    close=Decimal(705),
                    previous_close=Decimal("697.49"),
                    volume_shares=4_961_248,
                    amount=Decimal(3497193408),
                    is_trading=True,
                    special_treatment=SpecialTreatment.NONE,
                    source_id="baostock_sdk",
                ),
            )
        )

        warnings = sink.persist(
            batch_for(BackfillDataDomain.RAW_DAILY_BAR, payload),
            dataset_version_id="dataset:bars:v1",
        )

        self.assertEqual(parquet.bars[0].listing_id, "listing:XSHG:600519")
        self.assertTrue(any("current-known identity mapping" in item for item in warnings))
        fallback_query, fallback_params = next(
            (query, params)
            for query, params in connection.calls
            if "FROM canonical.listings" in query and "listed_on <=" in query
        )
        self.assertIn("exchange = %s", fallback_query)
        self.assertEqual(
            fallback_params,
            ("listing:XSHG:600519", "XSHG", date(2018, 1, 2), date(2018, 1, 2)),
        )

    def test_sink_applies_correction_only_with_batch_provider_scope(self) -> None:
        connection = ProviderCorrectionConnection()
        parquet = FakeParquetStore()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=parquet,  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = DailyObservationPayload(
            rows=(
                StagedDailyObservation(
                    code="SZ.300114",
                    exchange=Exchange.XSHE,
                    session_date=date(2024, 12, 31),
                    currency="CNY",
                    open=Decimal(10),
                    high=Decimal(11),
                    low=Decimal(9),
                    close=Decimal(10),
                    previous_close=Decimal(10),
                    volume_shares=100,
                    amount=Decimal(1000),
                    is_trading=True,
                    special_treatment=SpecialTreatment.NONE,
                    source_id="baostock_sdk",
                ),
            )
        )

        sink.persist(
            batch_for(BackfillDataDomain.RAW_DAILY_BAR, payload),
            dataset_version_id="dataset:bars:v1",
        )

        self.assertEqual(parquet.bars[0].listing_id, "listing:XSHE:302132")
        correction_params = next(
            params
            for query, params in connection.calls
            if "FROM canonical.provider_identifier_corrections" in query
            and "corrections.valid_from <=" in query
        )
        self.assertEqual(correction_params[0], "baostock_sdk")

    def test_current_known_listing_fallback_requires_exactly_one_compatible_row(self) -> None:
        class MultipleRowsResult(FakeResult):
            def fetchall(self) -> list[tuple[object, ...]]:
                return [
                    ("listing:XSHG:600519",),
                    ("listing:XSHG:600519:duplicate",),
                ]

        class AmbiguousFallbackConnection(FakeConnection):
            def execute(
                self, query: str, params: tuple[object, ...] = ()
            ) -> FakeResult:
                self.calls.append((query, params))
                if "FROM canonical.identifier_history AS identifiers" in query:
                    return FakeResult()
                if "FROM canonical.listings" in query and "listed_on <=" in query:
                    return MultipleRowsResult()
                return FakeResult((True,)) if "RETURNING" in query else FakeResult()

        sink = CanonicalBackfillSink(
            connection=AmbiguousFallbackConnection(),
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = DailyObservationPayload(
            rows=(
                StagedDailyObservation(
                    code="SH.600519",
                    exchange=Exchange.XSHG,
                    session_date=date(2018, 1, 2),
                    currency="CNY",
                    open=None,
                    high=None,
                    low=None,
                    close=None,
                    previous_close=None,
                    volume_shares=None,
                    amount=None,
                    is_trading=False,
                    special_treatment=SpecialTreatment.NONE,
                    source_id="baostock_sdk",
                ),
            )
        )

        with self.assertRaisesRegex(CanonicalSinkError, "unique compatible current identity"):
            sink.persist(
                batch_for(BackfillDataDomain.RAW_DAILY_BAR, payload),
                dataset_version_id="dataset:bars:v1",
            )

    def test_strict_pit_batch_never_queries_current_known_listing_fallback(self) -> None:
        connection = CurrentIdentityFallbackConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = DailyObservationPayload(rows=())
        strict_batch = replace(
            batch_for(BackfillDataDomain.RAW_DAILY_BAR, payload),
            trust_state=DataTrustState.PIT_VERIFIED,
        )

        with self.assertRaisesRegex(CanonicalSinkError, "only normalized_current"):
            sink.persist(strict_batch, dataset_version_id="dataset:strict:v1")

        self.assertEqual(connection.calls, [])

    def test_persists_calendar_with_explicit_provider_closure_reason(self) -> None:
        connection = FakeConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            listing_resolver=lambda _code, _as_of: "unused",
            clock=lambda: NOW,
        )
        payload = TradingCalendarPayload(
            rows=(
                StagedTradingCalendarDay(
                    exchange=Exchange.XSHG,
                    calendar_date=date(2018, 1, 1),
                    is_open=False,
                    closure_reason="provider_reported_closed",
                    source_id="baostock_sdk",
                ),
            )
        )

        sink.persist(
            batch_for(BackfillDataDomain.TRADING_CALENDAR, payload),
            dataset_version_id="dataset:test:v1",
        )

        query, params = connection.calls[-1]
        self.assertIn("INSERT INTO canonical.exchange_calendar_days", query)
        self.assertEqual(params[3], "provider_reported_closed")

    def test_persists_current_security_identity_without_inventing_industry_code(self) -> None:
        connection = FakeConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = SecurityMasterPayload(
            rows=(
                StagedSecurityIdentity(
                    code="SH.600519",
                    company_legal_name="贵州茅台酒股份有限公司",
                    security_name="贵州茅台",
                    exchange=Exchange.XSHG,
                    board=Board.MAIN,
                    listed_on=date(2001, 8, 27),
                    delisted_on=None,
                    listing_state=ListingState.ACTIVE,
                    observed_on=date(2026, 8, 10),
                    industry_taxonomy="证监会行业",
                    industry_code=None,
                    industry_name="酒、饮料和精制茶制造业",
                    identity_source_id="baostock_sdk.query_stock_basic",
                    legal_name_source_id="akshare.stock_profile_cninfo",
                    industry_source_id="baostock_sdk.query_stock_industry",
                ),
            )
        )

        sink.persist(
            batch_for(BackfillDataDomain.SECURITY_MASTER, payload),
            dataset_version_id="dataset:identity:v1",
        )

        sql = "\n".join(query for query, _params in connection.calls)
        for table in (
            "companies",
            "securities",
            "listings",
            "identifier_history",
            "listing_state_periods",
            "industry_memberships",
        ):
            self.assertIn(f"INSERT INTO {qualified_table(table)}", sql)
        industry_call = next(
            params for query, params in connection.calls if "INSERT INTO canonical.industry_memberships" in query
        )
        self.assertIsNone(industry_call[3])
        listing_state_call = next(
            params
            for query, params in connection.calls
            if "INSERT INTO canonical.listing_state_periods" in query
        )
        self.assertIsNone(listing_state_call[3])
        listing_state_sql = next(
            query
            for query, _params in connection.calls
            if "INSERT INTO canonical.listing_state_periods" in query
        )
        self.assertNotIn("'none'", listing_state_sql)

    def test_persists_historical_universe_as_research_only_until_tradability_is_evaluated(self) -> None:
        connection = FakeConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            listing_resolver=lambda code, _as_of: f"listing:{code}",
            clock=lambda: NOW,
        )
        payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2018, 1, 2),
                    valid_to=date(2018, 1, 4),
                    source_id="baostock_sdk.query_hs300_stocks",
                ),
            ),
        )

        sink.persist(
            batch_for(BackfillDataDomain.UNIVERSE, payload),
            dataset_version_id="dataset:universe:v1",
        )

        sql = "\n".join(query for query, _params in connection.calls)
        self.assertIn("INSERT INTO canonical.universe_definitions", sql)
        self.assertIn("INSERT INTO canonical.universe_versions", sql)
        version = next(
            params for query, params in connection.calls if "INSERT INTO canonical.universe_versions" in query
        )
        self.assertEqual(version[2], "dataset:universe:v1")
        self.assertEqual(version[4], DataTrustState.NORMALIZED_CURRENT.value)
        self.assertEqual(version[5], "baostock_sdk")
        self.assertIn("baostock_sdk.query_hs300_stocks", str(version[6]))
        self.assertEqual(version[7], NOW)
        self.assertEqual(version[8], NOW)
        self.assertIsNone(version[9])
        membership = next(
            params for query, params in connection.calls if "INSERT INTO canonical.universe_memberships" in query
        )
        self.assertTrue(membership[4])
        self.assertFalse(membership[5])
        self.assertIn("tradability_not_evaluated", str(membership[7]))
        self.assertEqual(membership[9], "baostock_sdk.query_hs300_stocks")

    def test_discrete_universe_version_persists_observed_dates_and_gaps(self) -> None:
        connection = FakeConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            listing_resolver=lambda code, _as_of: f"listing:{code}",
            clock=lambda: NOW,
        )
        payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2018, 1, 31),
                    valid_to=date(2018, 2, 1),
                    source_id="baostock_sdk.query_hs300_stocks:month_end_discrete",
                ),
            ),
            observation_mode=UniverseObservationMode.DISCRETE_MONTH_END,
            observed_dates=(date(2018, 1, 31),),
            unobserved_intervals=((date(2018, 1, 1), date(2018, 1, 31)),),
        )

        sink.persist(
            batch_for(BackfillDataDomain.UNIVERSE, payload),
            dataset_version_id="dataset:universe:discrete:v1",
        )

        version = next(
            params
            for query, params in connection.calls
            if "INSERT INTO canonical.universe_versions" in query
        )
        self.assertEqual(version[10], "discrete_month_end")
        self.assertIn("2018-01-31", str(version[11]))
        self.assertIn("2018-01-01", str(version[12]))

    def test_universe_identity_preflight_finishes_before_any_version_write(self) -> None:
        connection = FakeConnection()

        def resolver(code: str, _as_of: date) -> str:
            if code == "SZ.302132":
                raise CanonicalSinkError("official alias is missing")
            return f"listing:{code}"

        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            listing_resolver=resolver,
            clock=lambda: NOW,
        )
        payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2026, 8, 10),
                    valid_to=date(2026, 8, 11),
                    source_id="baostock_sdk.query_hs300_stocks",
                ),
                StagedUniverseMembership(
                    code="SZ.302132",
                    valid_from=date(2026, 8, 10),
                    valid_to=date(2026, 8, 11),
                    source_id="baostock_sdk.query_hs300_stocks",
                ),
            ),
        )

        with self.assertRaisesRegex(CanonicalSinkError, "identity preflight"):
            sink.persist(
                batch_for(BackfillDataDomain.UNIVERSE, payload),
                dataset_version_id="dataset:universe:v1",
            )

        sql = "\n".join(query for query, _params in connection.calls)
        self.assertNotIn("INSERT INTO canonical.universe_definitions", sql)
        self.assertNotIn("INSERT INTO canonical.universe_versions", sql)

    def test_normalized_current_universe_is_rejected_by_strict_pit_reader(self) -> None:
        row = (
            "universe:000300:dataset:universe:v1",
            "csi:000300",
            "dataset:universe:v1",
            NOW,
            DataTrustState.NORMALIZED_CURRENT.value,
            "a_share_identity_universe",
            ["baostock_sdk.query_hs300_stocks"],
            NOW,
            NOW,
            None,
            UniverseObservationMode.CONTINUOUS_DAILY.value,
            [],
            [],
        )

        class UniverseReadConnection(FakeConnection):
            def execute(
                self, query: str, params: tuple[object, ...] = ()
            ) -> FakeResult:
                self.calls.append((query, params))
                if "FROM canonical.universe_versions" in query:
                    return FakeResult(row)
                return FakeResult()

        sink = CanonicalBackfillSink(
            connection=UniverseReadConnection(),
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )

        with self.assertRaisesRegex(CanonicalSinkError, "strict PIT"):
            sink.get_universe_version(
                "universe:000300:dataset:universe:v1",
                require_pit_verified=True,
            )

        restored = sink.get_universe_version(
            "universe:000300:dataset:universe:v1",
            require_pit_verified=False,
        )
        assert restored is not None
        self.assertEqual(restored.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(restored.dataset_version_id, "dataset:universe:v1")
        self.assertEqual(restored.retrieved_at, NOW)
        self.assertEqual(restored.system_as_of, NOW)
        self.assertEqual(
            restored.source_ids, ("baostock_sdk.query_hs300_stocks",)
        )
        self.assertEqual(
            restored.observation_mode,
            UniverseObservationMode.CONTINUOUS_DAILY,
        )
        self.assertEqual(restored.observed_dates, ())
        self.assertEqual(restored.unobserved_intervals, ())

    def test_same_benchmark_annual_checkpoints_have_distinct_stable_versions(self) -> None:
        connection = FakeConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            listing_resolver=lambda code, _as_of: f"listing:{code}",
            clock=lambda: NOW.replace(hour=23),
        )
        first_payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2018, 1, 2),
                    valid_to=date(2018, 12, 29),
                    source_id="baostock_sdk.query_hs300_stocks",
                ),
            ),
        )
        first = batch_for(BackfillDataDomain.UNIVERSE, first_payload)
        second_payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2019, 1, 2),
                    valid_to=date(2019, 12, 29),
                    source_id="baostock_sdk.query_hs300_stocks",
                ),
            ),
        )
        second = replace(
            first,
            work_unit=replace(
                first.work_unit,
                checkpoint_key="universe:index-000300:ALL:2019-01-01:2019-12-31",
                start_date=date(2019, 1, 1),
                end_date=date(2019, 12, 31),
            ),
            payload=second_payload,
        )

        sink.persist(first, dataset_version_id="dataset:universe:v1")
        sink.persist(second, dataset_version_id="dataset:universe:v1")
        sink.persist(first, dataset_version_id="dataset:universe:v1")

        versions = [
            params
            for query, params in connection.calls
            if "INSERT INTO canonical.universe_versions" in query
        ]
        self.assertEqual(len(versions), 3)
        self.assertNotEqual(versions[0][0], versions[1][0])
        self.assertEqual(versions[0][:6], versions[2][:6])
        self.assertEqual(str(versions[0][6]), str(versions[2][6]))
        self.assertEqual(versions[0][7:11], versions[2][7:11])
        self.assertEqual(str(versions[0][11]), str(versions[2][11]))
        self.assertEqual(str(versions[0][12]), str(versions[2][12]))
        self.assertEqual(versions[0][7], first.metadata.retrieved_at)
        self.assertEqual(versions[0][8], first.metadata.retrieved_at)

    def test_same_effective_date_correction_fails_closed_instead_of_do_nothing(self) -> None:
        class ConflictConnection(FakeConnection):
            def execute(
                self, query: str, params: tuple[object, ...] = ()
            ) -> FakeResult:
                self.calls.append((query, params))
                if "RETURNING" in query and "INSERT INTO canonical.identifier_history" in query:
                    return FakeResult()
                if "RETURNING" in query:
                    return FakeResult((True,))
                return FakeResult()

        sink = CanonicalBackfillSink(
            connection=ConflictConnection(),
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = SecurityMasterPayload(
            rows=(
                StagedSecurityIdentity(
                    code="SH.600519",
                    company_legal_name="贵州茅台酒股份有限公司",
                    security_name="贵州茅台",
                    exchange=Exchange.XSHG,
                    board=Board.MAIN,
                    listed_on=date(2001, 8, 27),
                    delisted_on=None,
                    listing_state=ListingState.ACTIVE,
                    observed_on=date(2026, 8, 10),
                    industry_taxonomy=None,
                    industry_code=None,
                    industry_name=None,
                    identity_source_id="baostock_sdk.query_stock_basic",
                    legal_name_source_id="akshare.stock_profile_cninfo",
                    industry_source_id=None,
                ),
            )
        )

        with self.assertRaisesRegex(CanonicalSinkError, "same effective date"):
            sink.persist(
                batch_for(BackfillDataDomain.SECURITY_MASTER, payload),
                dataset_version_id="dataset:identity:v1",
            )

    def test_idempotent_upserts_never_update_generated_identity_columns(self) -> None:
        source = inspect.getsource(CanonicalBackfillSink)

        for column in (
            "identifier_history_id",
            "listing_state_period_id",
            "industry_membership_id",
            "universe_membership_id",
        ):
            with self.subTest(column=column):
                self.assertNotIn(f"{column} =", source)

    def test_historical_universe_fallback_requires_a_compatible_listing_interval(self) -> None:
        connection = CurrentIdentityFallbackConnection()
        sink = CanonicalBackfillSink(
            connection=connection,
            parquet_store=FakeParquetStore(),  # type: ignore[arg-type]
            clock=lambda: NOW,
        )
        payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2018, 1, 2),
                    valid_to=date(2018, 1, 4),
                    source_id="baostock_sdk.query_hs300_stocks",
                ),
            ),
        )

        sink.persist(
            batch_for(BackfillDataDomain.UNIVERSE, payload),
            dataset_version_id="dataset:universe:v1",
        )

        self.assertTrue(
            any("listed_on <=" in query for query, _params in connection.calls)
        )
        membership = next(
            params for query, params in connection.calls if "INSERT INTO canonical.universe_memberships" in query
        )
        self.assertEqual(membership[1], "listing:XSHG:600519")

if __name__ == "__main__":
    unittest.main()
