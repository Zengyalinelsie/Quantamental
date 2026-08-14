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
        if query.startswith("SELECT version FROM public.schema_migrations"):
            return FakeResult(params[0] if str(params[0]) in self.applied else None)
        if query.startswith("INSERT INTO public.schema_migrations"):
            self.applied.add(str(params[0]))
        return FakeResult()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class MigrationRunnerTest(unittest.TestCase):
    def test_migration_ledger_is_explicitly_kept_in_public(self) -> None:
        connection = FakeConnection()
        with tempfile.TemporaryDirectory() as directory:
            migration = Path(directory) / "0001_initial.sql"
            migration.write_text("SELECT 1", encoding="utf-8")
            apply_migrations(connection, Path(directory))

        sql = "\n".join(query for query, _params in connection.calls)
        self.assertIn("CREATE TABLE IF NOT EXISTS public.schema_migrations", sql)
        self.assertIn("SELECT version FROM public.schema_migrations", sql)
        self.assertIn("INSERT INTO public.schema_migrations", sql)

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
                "0015_timing_benchmark_bars.sql",
                "0016_financial_backfill_dimensions.sql",
                "0017_feature_snapshots_and_research_labels.sql",
                "0018_normalized_current_financial_backfill.sql",
                "0019_identifier_alias_scopes.sql",
                "0020_market_structure_observations.sql",
                "0021_provider_mapping_usage_scopes.sql",
                "0022_discrete_universe_observations.sql",
                "0023_normalized_current_financial_identity.sql",
                "0024_identifier_alias_append_only_reconciliation.sql",
                "0025_experiment_runs.sql",
                "0026_empty_financial_periods.sql",
                "0027_factor_promotion_reviews.sql",
                "0028_factor_qualification_audits.sql",
                "0029_layered_schemas.sql",
                "0030_p5_investment_signal_ledgers.sql",
                "0031_p5_frozen_valuation_inputs.sql",
            ),
        )

    def test_p5_frozen_valuation_inputs_are_exact_append_only_and_fail_closed(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0031_p5_frozen_valuation_inputs.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE research.valuation_input_bundles",
            "ALTER TABLE canonical.industry_memberships",
            "industry_membership_qualification_complete",
            "latest_source_available_at <= decision_time",
            "data_mode <> 'strict_historical' OR trust_state = 'pit_verified'",
            "jsonb_array_length(dataset_version_ids) > 0",
            "bundle_document ->> 'bundle_version_id' = bundle_version_id",
            "BEFORE UPDATE OR DELETE ON research.valuation_input_bundles",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_p5_ledgers_are_layered_append_only_and_api_isolated(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0030_p5_investment_signal_ledgers.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE research.investment_views",
            "CREATE TABLE research.investment_view_outcomes",
            "CREATE TABLE research.expected_return_calibrations",
            "CREATE TABLE research.signal_snapshots",
            "UNIQUE (view_id)",
            "UNIQUE (outcome_id)",
            "BEFORE UPDATE OR DELETE ON research.investment_views",
            "BEFORE UPDATE OR DELETE ON research.investment_view_outcomes",
            "BEFORE UPDATE OR DELETE ON research.expected_return_calibrations",
            "BEFORE UPDATE OR DELETE ON research.signal_snapshots",
            "CREATE VIEW serving.research_signal_snapshots",
            "approval_scope = 'research_backtest'",
            "CREATE VIEW serving.production_signal_snapshots",
            "approval_scope IN ('shadow', 'paper', 'limited_live')",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_factor_qualification_audits_are_failed_append_only_evidence(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0028_factor_qualification_audits.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE factor_validation_reports",
            "CREATE TABLE factor_qualification_audits",
            "readiness_permitted = FALSE",
            "factor_lifecycle_status IN ('draft', 'research')",
            "factor_qualification_audits_append_only",
            "factor_validation_reports_append_only",
            "BEFORE UPDATE OR DELETE ON factor_qualification_audits",
            "BEFORE UPDATE OR DELETE ON factor_validation_reports",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_factor_reviews_are_scoped_science_gated_and_append_only(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0027_factor_promotion_reviews.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE factor_promotion_reviews",
            "factor_lifecycle_status = 'candidate'",
            "decision <> 'approved' OR scientific_gate_passed",
            "reviewer_role IN ('reviewer', 'administrator')",
            "scope IN ('research_backtest', 'shadow', 'paper', 'limited_live')",
            "factor_promotion_reviews_append_only",
            "BEFORE UPDATE OR DELETE ON factor_promotion_reviews",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_empty_financial_period_migration_preserves_explicit_absence(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0026_empty_financial_periods.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "observation_count >= 0",
            "jsonb_typeof(observation_ids) = 'array'",
            "no_observations",
            "observation_count = jsonb_array_length(observation_ids)",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_experiment_storage_freezes_specs_runs_and_failure_evidence(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0025_experiment_runs.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE experiment_specs",
            "CREATE TABLE experiment_runs",
            "FOREIGN KEY (spec_id, spec_hash)",
            "failed",
            "failure_evidence IS NOT NULL",
            "experiment_specs_append_only",
            "experiment_runs_append_only",
            "BEFORE UPDATE OR DELETE ON experiment_specs",
            "BEFORE UPDATE OR DELETE ON experiment_runs",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_discrete_universe_migration_preserves_observed_dates_and_gaps(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0022_discrete_universe_observations.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "ADD COLUMN observation_mode TEXT NOT NULL",
            "ADD COLUMN observed_dates JSONB NOT NULL",
            "ADD COLUMN unobserved_intervals JSONB NOT NULL",
            "discrete_month_end",
            "jsonb_array_length(observed_dates) > 0",
            "CREATE VIEW strict_pit_universe_versions",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)
        for column in (
            "observation_mode",
            "observed_dates",
            "unobserved_intervals",
        ):
            with self.subTest(dropped_default=column):
                self.assertIn(
                    f"ALTER COLUMN {column} DROP DEFAULT",
                    normalized_sql,
                )

    def test_identifier_alias_migration_separates_official_and_provider_scope(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0019_identifier_alias_scopes.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE official_identifier_aliases",
            "evidence_url",
            "published_on",
            "CREATE TABLE provider_identifier_corrections",
            "provider_id TEXT NOT NULL",
            "recorded_at TIMESTAMPTZ NOT NULL",
            "official_identifier_aliases_append_only",
            "provider_identifier_corrections_append_only",
            "BEFORE UPDATE OR DELETE ON official_identifier_aliases",
            "BEFORE UPDATE OR DELETE ON provider_identifier_corrections",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_identifier_alias_append_only_reconciliation_is_forward_only(self) -> None:
        sql = (
            PLATFORM_ROOT
            / "migrations"
            / "0024_identifier_alias_append_only_reconciliation.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            (
                "DROP TRIGGER IF EXISTS official_identifier_aliases_append_only "
                "ON official_identifier_aliases"
            ),
            (
                "DROP TRIGGER IF EXISTS provider_identifier_corrections_append_only "
                "ON provider_identifier_corrections"
            ),
            "CREATE OR REPLACE FUNCTION prevent_identifier_alias_mutation()",
            (
                "CREATE TRIGGER official_identifier_aliases_append_only "
                "BEFORE UPDATE OR DELETE ON official_identifier_aliases"
            ),
            (
                "CREATE TRIGGER provider_identifier_corrections_append_only "
                "BEFORE UPDATE OR DELETE ON provider_identifier_corrections"
            ),
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

        self.assertLess(
            normalized_sql.index(
                "DROP TRIGGER IF EXISTS official_identifier_aliases_append_only"
            ),
            normalized_sql.index("CREATE TRIGGER official_identifier_aliases_append_only"),
        )
        self.assertLess(
            normalized_sql.index(
                "DROP TRIGGER IF EXISTS provider_identifier_corrections_append_only"
            ),
            normalized_sql.index("CREATE TRIGGER provider_identifier_corrections_append_only"),
        )
        for forbidden_data_mutation in (
            "UPDATE canonical.official_identifier_aliases SET",
            "DELETE FROM canonical.official_identifier_aliases",
            "UPDATE canonical.provider_identifier_corrections SET",
            "DELETE FROM canonical.provider_identifier_corrections",
        ):
            with self.subTest(forbidden_data_mutation=forbidden_data_mutation):
                self.assertNotIn(forbidden_data_mutation, normalized_sql)

    def test_feature_and_research_label_storage_is_physically_separate_and_append_only(self) -> None:
        sql = (
            PLATFORM_ROOT
            / "migrations"
            / "0017_feature_snapshots_and_research_labels.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "CREATE TABLE feature_snapshots",
            "CREATE TABLE research_labels",
            "dataset_version_ids",
            "input_content_hashes",
            "feature_snapshots_append_only",
            "research_labels_append_only",
            "BEFORE UPDATE OR DELETE ON feature_snapshots",
            "BEFORE UPDATE OR DELETE ON research_labels",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

    def test_financial_backfill_reuses_ledgers_with_explicit_work_unit_dimensions(self) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0016_financial_backfill_dimensions.sql"
        ).read_text(encoding="utf-8")
        normalized_sql = " ".join(sql.split())
        for contract in (
            "financial_statement",
            "statement_type",
            "provider_table",
            "report_period_end",
            "symbol_bucket_id",
            "symbol_count",
            "provider_profile_version",
            "universe_version_id",
            "mapping_version_id",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized_sql)

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
