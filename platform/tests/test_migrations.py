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
            ),
        )

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
