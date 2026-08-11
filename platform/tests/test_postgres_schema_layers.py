import re
import unittest
from pathlib import Path

from a_share_platform.adapters.postgres.schema_layers import (
    PERSISTENT_TABLE_SCHEMAS,
    SchemaLayer,
    qualified_table,
)

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PLATFORM_ROOT / "src" / "a_share_platform"


class PostgresSchemaLayerContractTest(unittest.TestCase):
    def test_six_layers_and_all_49_persistent_tables_have_one_owner(self) -> None:
        self.assertEqual(
            {layer.value for layer in SchemaLayer},
            {
                "governance",
                "evidence",
                "observation",
                "canonical",
                "research",
                "serving",
            },
        )
        self.assertEqual(len(PERSISTENT_TABLE_SCHEMAS), 49)
        self.assertEqual(
            qualified_table("financial_fact_observations"),
            "canonical.financial_fact_observations",
        )
        self.assertEqual(
            qualified_table("normalized_current_financial_observations"),
            "observation.normalized_current_financial_observations",
        )
        self.assertEqual(
            qualified_table("factor_promotion_reviews"),
            "governance.factor_promotion_reviews",
        )
        with self.assertRaisesRegex(KeyError, "unknown persistent table"):
            qualified_table("made_up_table")

    def test_layering_migration_moves_every_table_and_the_serving_view(self) -> None:
        sql = (PLATFORM_ROOT / "migrations" / "0029_layered_schemas.sql").read_text(
            encoding="utf-8"
        )
        normalized = " ".join(sql.split())
        for layer in SchemaLayer:
            self.assertIn(f"CREATE SCHEMA {layer.value}", normalized)
        for table, layer in PERSISTENT_TABLE_SCHEMAS.items():
            with self.subTest(table=table):
                self.assertEqual(
                    normalized.count(
                        f"ALTER TABLE public.{table} SET SCHEMA {layer.value}"
                    ),
                    1,
                )
        self.assertIn(
            "ALTER VIEW public.strict_pit_universe_versions SET SCHEMA serving",
            normalized,
        )
        self.assertIn(
            "FROM research.experiment_runs",
            normalized,
        )
        self.assertNotIn("ALTER TABLE public.schema_migrations", normalized)
        self.assertNotIn("UPDATE ", normalized)
        self.assertNotIn("INSERT ", normalized)
        self.assertNotIn("DELETE ", normalized)

    def test_runtime_persistent_sql_is_schema_qualified(self) -> None:
        operation = (
            r"(?:FROM|JOIN|INSERT\s+INTO|UPDATE|DELETE\s+FROM|REFERENCES|"
            r"ALTER\s+TABLE|LOCK\s+TABLE)"
        )
        failures: list[str] = []
        for path in sorted(SOURCE_ROOT.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for table in PERSISTENT_TABLE_SCHEMAS:
                pattern = re.compile(rf"\b{operation}\s+{re.escape(table)}\b", re.IGNORECASE)
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    failures.append(f"{path.relative_to(PLATFORM_ROOT)}:{line}:{table}")
        self.assertEqual(failures, [], "unqualified persistent SQL:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
