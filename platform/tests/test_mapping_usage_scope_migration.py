import unittest
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]


class MappingUsageScopeMigrationTest(unittest.TestCase):
    def test_migration_replaces_ambiguous_boolean_with_fail_closed_scopes(self) -> None:
        sql = (
            PLATFORM_ROOT
            / "migrations"
            / "0021_provider_mapping_usage_scopes.sql"
        ).read_text(encoding="utf-8")
        normalized = " ".join(sql.split())

        for contract in (
            "ADD COLUMN allowed_use_scopes TEXT[]",
            "current_research",
            "strict_historical",
            "production",
            "DROP COLUMN production_allowed",
            "method <> 'fuzzy'",
            "provider_id NOT IN ('akshare', 'provider:akshare')",
            "DROP DEFAULT",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized)


if __name__ == "__main__":
    unittest.main()
