import unittest
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "0023_normalized_current_financial_identity.sql"
)


class FinancialCurrentIdentityMigrationTest(unittest.TestCase):
    def test_identity_method_is_explicit_and_old_rows_keep_narrow_semantics(self) -> None:
        sql = MIGRATION.read_text(encoding="utf-8")

        self.assertIn("ADD COLUMN identity_resolution_method TEXT", sql)
        self.assertIn("effective_dated_report_period", sql)
        self.assertIn("current_known_retrieval_date", sql)
        self.assertIn("FROM pg_constraint", sql)
        self.assertIn("pg_get_constraintdef(oid)", sql)
        self.assertIn("identity_as_of = report_period_end", sql)
        self.assertIn("DROP CONSTRAINT %I", sql)
        self.assertIn("legacy_identity_constraint", sql)
        self.assertNotIn(
            "DROP CONSTRAINT normalized_current_financial_observations_check,",
            sql,
        )
        self.assertIn("identity_as_of = (retrieved_at AT TIME ZONE 'UTC')::date", sql)
        self.assertIn("ALTER COLUMN identity_resolution_method DROP DEFAULT", sql)
        self.assertIn("ALTER TABLE financial_backfill_persist_receipts", sql)
        self.assertIn("financial_backfill_receipts_identity_method_check", sql)


if __name__ == "__main__":
    unittest.main()
