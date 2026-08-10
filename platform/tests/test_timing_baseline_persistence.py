import unittest
from datetime import date
from pathlib import Path

from a_share_platform.adapters.postgres.timing_baseline import (
    PostgresTimingBaselineStore,
)

PLATFORM_ROOT = Path(__file__).resolve().parents[1]


class FakeResult:
    def fetchone(self) -> tuple[object, ...]:
        return (1,)

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        return FakeResult()


class TimingBaselinePersistenceTest(unittest.TestCase):
    def test_universe_lookup_maps_canonical_index_id_to_persisted_csi_code(self) -> None:
        connection = FakeConnection()
        store = PostgresTimingBaselineStore(connection)

        self.assertTrue(
            store.has_universe_version(
                benchmark_id="index:000905",
                universe_version_id="universe:000905:dataset:test",
                effective_session=date(2026, 8, 10),
            )
        )

        query, params = connection.calls[-1]
        self.assertIn("definition.benchmark_id = %s", query)
        self.assertIn("FROM universe_memberships", query)
        self.assertIn("membership.valid_from <= %s", query)
        self.assertIn("%s < membership.valid_to", query)
        self.assertEqual(
            params,
            (
                "universe:000905:dataset:test",
                "000905",
                date(2026, 8, 10),
                date(2026, 8, 10),
            ),
        )

    def test_migration_keeps_real_benchmark_bars_current_unadjusted_and_immutable(
        self,
    ) -> None:
        sql = (
            PLATFORM_ROOT / "migrations" / "0015_timing_benchmark_bars.sql"
        ).read_text(encoding="utf-8")
        normalized = " ".join(sql.split())
        for contract in (
            "CREATE TABLE timing_benchmark_bars",
            "benchmark_id IN ('index:000300', 'index:000905')",
            "unadjusted_close NUMERIC NOT NULL",
            "adjustment_mode = 'unadjusted'",
            "trust_state = 'normalized_current'",
            "data_mode = 'current_research'",
            "dataset_version_id TEXT NOT NULL REFERENCES dataset_versions",
            "CREATE TRIGGER timing_benchmark_bars_append_only",
        ):
            with self.subTest(contract=contract):
                self.assertIn(contract, normalized)


if __name__ == "__main__":
    unittest.main()
