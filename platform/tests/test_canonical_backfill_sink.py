import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from a_share_platform.adapters.postgres.dataset_versions import (
    PostgresDatasetVersionRepository,
)
from a_share_platform.adapters.providers.backfill_payloads import (
    DailyObservationPayload,
    StagedDailyObservation,
    StagedTradingCalendarDay,
    TradingCalendarPayload,
)
from a_share_platform.adapters.sinks.canonical_backfill import CanonicalBackfillSink
from a_share_platform.application.backfill import (
    BackfillPlanner,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import (
    BackfillBatch,
    BackfillDataDomain,
    DatasetQualityStatus,
    ProviderRetrievalMetadata,
)
from a_share_platform.domain.governance import DatasetVersion, VersionConflictError
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import Exchange, SpecialTreatment

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
        connection = FakeConnection(
            (value.dataset_version_id, value.content_hash, value.created_at, value.schema_version)
        )
        repository = PostgresDatasetVersionRepository(connection)

        self.assertEqual(repository.register_dataset(value), value)
        self.assertIn("INSERT INTO dataset_versions", connection.calls[0][0])
        self.assertIn("SELECT dataset_version_id", connection.calls[1][0])

        conflict_connection = FakeConnection(
            (value.dataset_version_id, "sha256:" + "b" * 64, value.created_at, value.schema_version)
        )
        with self.assertRaises(VersionConflictError):
            PostgresDatasetVersionRepository(conflict_connection).register_dataset(value)

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
        self.assertIn("INSERT INTO daily_market_states", sql)
        self.assertIn("INSERT INTO market_data_partitions", sql)

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
        self.assertIn("INSERT INTO exchange_calendar_days", query)
        self.assertEqual(params[3], "provider_reported_closed")


if __name__ == "__main__":
    unittest.main()
