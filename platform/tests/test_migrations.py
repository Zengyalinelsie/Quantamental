import tempfile
import unittest
from pathlib import Path

from a_share_platform.adapters.postgres.migrations import apply_migrations, discover_migrations

PLATFORM_ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def __init__(self, value: object | None = None) -> None:
        self.value = value

    def fetchone(self) -> object | None:
        return self.value


class FakeConnection:
    def __init__(self, *, applied: set[str] | None = None, fail_sql: str | None = None) -> None:
        self.applied = applied or set()
        self.fail_sql = fail_sql
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if self.fail_sql and self.fail_sql in query:
            raise RuntimeError("migration failed")
        if query.startswith("SELECT version"):
            return FakeResult(params[0] if str(params[0]) in self.applied else None)
        if query.startswith("INSERT INTO schema_migrations"):
            self.applied.add(str(params[0]))
        return FakeResult()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class MigrationRunnerTest(unittest.TestCase):
    def test_platform_migrations_are_versioned_in_order(self) -> None:
        self.assertEqual(
            tuple(path.name for path in discover_migrations(PLATFORM_ROOT / "migrations")),
            (
                "0001_governance_ledger.sql",
                "0002_security_master.sql",
                "0003_universe.sql",
                "0004_market_data.sql",
                "0005_data_backfill.sql",
                "0006_disclosure_evidence.sql",
                "0007_canonical_metrics.sql",
                "0008_financial_facts.sql",
                "0009_nullable_industry_code.sql",
                "0010_canonical_universe_lineage.sql",
                "0011_domain_aware_checkpoint_adjustment.sql",
                "0012_timing_shadow_ledger.sql",
                "0013_disclosure_time_precision.sql",
            ),
        )

    def test_disclosure_precision_migration_distinguishes_date_only_metadata(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0013_disclosure_time_precision.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "ADD COLUMN publication_time_precision",
            "publication_time_precision IN ('exact', 'date_only')",
            "date_only",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_timing_shadow_migration_is_append_only_and_keeps_required_context(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0012_timing_shadow_ledger.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE timing_forecasts",
            "data_mode = 'current_research'",
            "deployment_stage = 'shadow'",
            "input_trust_state IN ('normalized_current', 'pit_verified')",
            "UNIQUE (benchmark_id, universe_version_id, effective_session)",
            "jsonb_array_length(horizon_forecasts) = 4",
            "passive_exposure_ratio",
            "active_adjustment",
            "dataset_version_ids",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_checkpoint_adjustment_mode_is_domain_aware(self) -> None:
        sql = (
            PLATFORM_ROOT
            / "migrations"
            / "0011_domain_aware_checkpoint_adjustment.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "DROP CONSTRAINT ingestion_checkpoints_adjustment_mode_check",
            "SET adjustment_mode = 'not_applicable'",
            "data_domain <> 'raw_daily_bar'",
            "data_domain = 'raw_daily_bar' AND adjustment_mode = 'unadjusted'",
            "data_domain <> 'raw_daily_bar' AND adjustment_mode = 'not_applicable'",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_missing_provider_industry_code_remains_null_instead_of_a_sentinel(self) -> None:
        sql = (PLATFORM_ROOT / "migrations" / "0009_nullable_industry_code.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("ALTER COLUMN industry_code DROP NOT NULL", sql)

    def test_canonical_universe_lineage_is_complete_and_strict_pit_isolated(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0010_canonical_universe_lineage.sql"
        ).read_text(encoding="utf-8")
        for contract in (
            "ALTER COLUMN special_treatment DROP NOT NULL",
            "ADD COLUMN trust_state TEXT NOT NULL",
            "ADD COLUMN provider_id TEXT NOT NULL",
            "ADD COLUMN source_ids JSONB NOT NULL",
            "ADD COLUMN retrieved_at TIMESTAMPTZ NOT NULL",
            "ADD COLUMN system_as_of TIMESTAMPTZ NOT NULL",
            "ADD COLUMN available_at TIMESTAMPTZ",
            "dataset_version_id",
            "trust_state = 'pit_verified'",
            "trust_state = 'normalized_current'",
            "CREATE VIEW strict_pit_universe_versions",
            "WHERE trust_state = 'pit_verified'",
            "jsonb_typeof(metadata) = 'object'",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)

    def test_disclosure_migration_preserves_raw_evidence_and_public_versions(self) -> None:
        sql = (PLATFORM_ROOT / "migrations" / "0006_disclosure_evidence.sql").read_text(
            encoding="utf-8"
        )
        for contract in (
            "CREATE TABLE raw_objects",
            "content_hash",
            "license_id",
            "retention_policy",
            "CREATE TABLE official_disclosures",
            "published_at",
            "available_at",
            "first_tradable_at",
            "supersedes_disclosure_id",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)

    def test_metric_registry_migration_blocks_fuzzy_production_mappings(self) -> None:
        sql = (PLATFORM_ROOT / "migrations" / "0007_canonical_metrics.sql").read_text(
            encoding="utf-8"
        )
        for contract in (
            "CREATE TABLE canonical_metrics",
            "CREATE TABLE metric_mapping_versions",
            "CREATE TABLE provider_field_mappings",
            "method <> 'fuzzy' OR production_allowed = FALSE",
            "CREATE TABLE financial_quality_rules",
            "CREATE TABLE unmapped_metric_fields",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)

    def test_financial_fact_migration_preserves_bitemporal_and_lineage_contracts(self) -> None:
        sql = (PLATFORM_ROOT / "migrations" / "0008_financial_facts.sql").read_text(
            encoding="utf-8"
        )
        for contract in (
            "CREATE TABLE financial_fact_observations",
            "company_id",
            "security_id",
            "report_period_end",
            "announced_at",
            "available_at",
            "known_from",
            "known_to",
            "revision_sequence",
            "provider_id",
            "raw_object_hash",
            "trust_state",
            "quality_state",
            "mapping_version_id",
            "dataset_version_id",
            "quality_issue_ids",
            "CREATE TABLE financial_authority_rules",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, sql)

    def test_discovers_and_applies_unseen_migrations_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "0002_second.sql").write_text("SELECT 2;", encoding="utf-8")
            (root / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
            connection = FakeConnection(applied={"0001_first"})
            self.assertEqual(
                tuple(path.name for path in discover_migrations(root)),
                ("0001_first.sql", "0002_second.sql"),
            )
            self.assertEqual(apply_migrations(connection, root), ("0002_second",))
            self.assertEqual(connection.commits, 1)
            self.assertEqual(connection.rollbacks, 0)

    def test_failure_rolls_back_and_remains_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "0001_failure.sql").write_text("BROKEN MIGRATION", encoding="utf-8")
            connection = FakeConnection(fail_sql="BROKEN")
            with self.assertRaisesRegex(RuntimeError, "migration failed"):
                apply_migrations(connection, root)
            self.assertEqual(connection.commits, 0)
            self.assertEqual(connection.rollbacks, 1)


if __name__ == "__main__":
    unittest.main()
