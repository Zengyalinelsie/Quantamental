import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from a_share_platform.adapters.postgres.backfill import PostgresBackfillRepository
from a_share_platform.application.backfill import (
    build_csi_backfill_plan,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import (
    CSI_300_SCOPE,
    BackfillCheckpoint,
    BackfillCheckpointStatus,
    BackfillDataDomain,
    BackfillJob,
    BackfillQualification,
    ProviderRetrievalMetadata,
    UniverseObservationMode,
)

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self.row = row

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row

    def fetchall(self) -> list[tuple[object, ...]]:
        return [] if self.row is None else [self.row]


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        return FakeResult()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class PostgresBackfillTest(unittest.TestCase):
    def test_repository_exposes_explicit_checkpoint_transaction_boundaries(self) -> None:
        connection = FakeConnection()
        repository = PostgresBackfillRepository(connection)

        repository.commit()
        repository.rollback()

        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 1)

    def test_migration_reuses_dataset_versions_and_persists_audit_outputs(self) -> None:
        sql = (PLATFORM_ROOT / "migrations" / "0005_data_backfill.sql").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("CREATE TABLE dataset_versions", sql)
        for contract in (
            "CREATE TABLE ingestion_jobs",
            "CREATE TABLE ingestion_checkpoints",
            "CREATE TABLE dataset_quality_reports",
            "CREATE TABLE dataset_coverage_reports",
            "REFERENCES dataset_versions",
            "provider_cutoff_date",
            "retrieved_at",
            "adjustment_mode",
            "units",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)

    def test_repository_inserts_job_with_json_plan_and_qualification(self) -> None:
        connection = FakeConnection()
        repository = PostgresBackfillRepository(connection)
        value = build_csi_backfill_plan(
            plan_id="plan:pg:v1",
            provider_id="a_share_mcp_baostock",
            end_date=date(2026, 8, 8),
            created_at=NOW,
        )
        qualification = BackfillQualification(
            provider_id=value.provider_id,
            permitted=False,
            evaluated_at=NOW,
            blockers=("license blocked",),
            warnings=("normalized_current only",),
        )
        job = BackfillJob.blocked(value, qualification)
        repository.save_job(job)
        query, params = connection.calls[-1]
        self.assertIn("INSERT INTO ingestion_jobs", query)
        self.assertIn("ON CONFLICT (job_id) DO NOTHING", query)
        self.assertEqual(params[0], job.job_id)
        self.assertEqual(params[2], "a_share_mcp_baostock")
        self.assertEqual(params[3], "blocked")

    def test_checkpoint_round_trip_preserves_real_provider_provenance(self) -> None:
        metadata = ProviderRetrievalMetadata(
            provider_id="futu_quote",
            retrieved_at=NOW,
            cutoff_date=date(2018, 1, 2),
            adjustment_mode="unadjusted",
            units=(("volume", "shares"),),
            warnings=("normalized_current only",),
        )
        checkpoint = BackfillCheckpoint.pending(
            job_id="job:roundtrip",
            checkpoint_key="raw:index-000300:XSHG:2018",
            scope_id=CSI_300_SCOPE.scope_id,
            domain=BackfillDataDomain.RAW_DAILY_BAR,
            market="XSHG",
            start_date=date(2018, 1, 1),
            end_date=date(2018, 12, 31),
            at=NOW,
        ).transition(BackfillCheckpointStatus.RUNNING, at=NOW)
        checkpoint = checkpoint.transition(
            BackfillCheckpointStatus.SUCCEEDED,
            at=NOW,
            processed_rows=242,
            content_hash="sha256:" + "b" * 64,
            retrieval_metadata=metadata,
        )
        connection = FakeConnection()
        repository = PostgresBackfillRepository(connection)
        repository.save_checkpoint(checkpoint)
        _query, params = connection.calls[-1]
        self.assertEqual(params[12], "futu_quote")

        row = (
            checkpoint.job_id,
            checkpoint.checkpoint_key,
            checkpoint.scope_id,
            checkpoint.domain.value,
            checkpoint.market,
            checkpoint.start_date,
            checkpoint.end_date,
            checkpoint.status.value,
            checkpoint.updated_at,
            checkpoint.processed_rows,
            checkpoint.rejected_rows,
            checkpoint.content_hash,
            checkpoint.cursor,
            checkpoint.error,
            metadata.provider_id,
            metadata.cutoff_date,
            metadata.retrieved_at,
            metadata.adjustment_mode,
            dict(metadata.units),
            list(metadata.warnings),
        )
        restored = repository._checkpoint_from_row(row)
        self.assertEqual(restored.retrieval_metadata, metadata)

    def test_plan_json_round_trip_preserves_explicit_full_market_authorization(self) -> None:
        value = build_private_local_backfill_plan(
            plan_id="plan:all-a-share:v1",
            provider_id="a_share_identity_universe",
            symbols=(),
            all_a_share=True,
            domains=(BackfillDataDomain.SECURITY_MASTER, BackfillDataDomain.UNIVERSE),
            start_date=date(2018, 1, 1),
            end_date=date(2026, 8, 8),
            created_at=NOW,
            universe_observation_mode=UniverseObservationMode.DISCRETE_MONTH_END,
        )

        restored = PostgresBackfillRepository._plan_from_json(
            PostgresBackfillRepository._plan_json(value)
        )

        self.assertEqual(restored, value)
        self.assertTrue(restored.all_a_share)
        self.assertEqual(
            restored.universe_observation_mode,
            UniverseObservationMode.DISCRETE_MONTH_END,
        )


if __name__ == "__main__":
    unittest.main()
