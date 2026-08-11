import unittest
from dataclasses import replace

import psycopg

from a_share_platform.adapters.postgres.signals import PostgresSignalSnapshotRepository
from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.ports.signals import (
    SignalSnapshotLedgerConflict,
    SignalSnapshotLedgerUnavailable,
)
from tests.test_signal_snapshot_ledger import snapshot_for


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class FakeConnection:
    def __init__(
        self,
        rows: list[tuple[object, ...]] | None = None,
        *,
        execute_error: BaseException | None = None,
        insert_error: BaseException | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.execute_error = execute_error
        self.insert_error = insert_error
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def transaction(self):
        return self

    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> FakeResult:
        self.calls.append((query, params))
        if self.execute_error is not None:
            raise self.execute_error
        normalized = " ".join(query.split())
        if normalized.startswith("SET TRANSACTION READ ONLY"):
            return FakeResult()
        if normalized.startswith("INSERT INTO research.signal_snapshots"):
            if self.insert_error is not None:
                raise self.insert_error
            self.rows.append(tuple(params))
            return FakeResult()
        if "WHERE snapshot_id = %s" in normalized:
            return FakeResult([row for row in self.rows if row[0] == params[0]])
        if "WHERE universe_version_id = %s" in normalized:
            return FakeResult(
                [
                    row
                    for row in self.rows
                    if (row[5], row[2], row[3], row[4], row[10]) == params
                ]
            )
        if "FROM research.signal_snapshots" in normalized:
            return FakeResult(sorted(self.rows, key=lambda row: str(row[0])))
        return FakeResult()


class PostgresSignalSnapshotRepositoryTest(unittest.TestCase):
    def test_round_trip_restores_complete_jsonb_document_and_verifies_hash(self) -> None:
        value = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        row = PostgresSignalSnapshotRepository.to_row(value)
        repository = PostgresSignalSnapshotRepository(FakeConnection([row]))

        self.assertEqual(repository.get_snapshot(value.snapshot_id), value)

        tampered = list(row)
        tampered[1] = "0" * 64
        repository = PostgresSignalSnapshotRepository(FakeConnection([tuple(tampered)]))
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            repository.get_snapshot(value.snapshot_id)

        indexed_tamper = list(row)
        indexed_tamper[6] = value.rank + 1
        repository = PostgresSignalSnapshotRepository(
            FakeConnection([tuple(indexed_tamper)])
        )
        with self.assertRaisesRegex(ValueError, "indexed fields mismatch"):
            repository.get_snapshot(value.snapshot_id)

    def test_insert_is_schema_qualified_append_only_and_jsonb_backed(self) -> None:
        value = snapshot_for(ApprovalScope.SHADOW)
        connection = FakeConnection()
        repository = PostgresSignalSnapshotRepository(connection)

        self.assertEqual(repository.append_snapshot(value), value)
        query, params = next(
            call
            for call in connection.calls
            if "INSERT INTO research.signal_snapshots" in call[0]
        )
        self.assertIn("ON CONFLICT (snapshot_id) DO NOTHING", query)
        self.assertNotIn("UPDATE", query)
        self.assertEqual(params[0], value.snapshot_id)
        for required_column in (
            "rank",
            "universe_size",
            "investment_view_id",
            "investment_view_hash",
            "factor_version_ids",
            "factor_review_ids",
        ):
            with self.subTest(required_column=required_column):
                self.assertIn(required_column, query)
        self.assertEqual(params[2:11], (
            value.security_id,
            value.decision_time,
            value.horizon_trading_days,
            value.universe_version_id,
            value.rank,
            value.universe_size,
            value.investment_view_id,
            value.investment_view_hash,
            value.approval_scope.value,
        ))
        self.assertEqual(
            params[11:15],
            (
                value.run_context.data_mode.value,
                value.run_context.deployment_stage.value,
                value.trust_state.value,
                value.data_cutoff,
            ),
        )
        for index in (15, 16, 17):
            with self.subTest(jsonb_parameter=index):
                self.assertTrue(
                    hasattr(params[index], "obj") or isinstance(params[index], str)
                )
        self.assertEqual(params[18], value.created_at)

    def test_same_id_is_idempotent_and_different_content_conflicts(self) -> None:
        value = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        row = PostgresSignalSnapshotRepository.to_row(value)
        connection = FakeConnection([row])
        repository = PostgresSignalSnapshotRepository(connection)

        self.assertEqual(repository.append_snapshot(value), value)
        self.assertFalse(
            any("INSERT INTO research.signal_snapshots" in query for query, _ in connection.calls)
        )

        changed = replace(value, rank=13)
        with self.assertRaisesRegex(SignalSnapshotLedgerConflict, "snapshot_id"):
            repository.append_snapshot(changed)

    def test_natural_key_conflict_fails_closed_even_with_another_id(self) -> None:
        value = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        repository = PostgresSignalSnapshotRepository(
            FakeConnection([PostgresSignalSnapshotRepository.to_row(value)])
        )
        rewritten = replace(
            value,
            snapshot_id="signal-snapshot:alternate-id",
            rank=13,
        )

        with self.assertRaisesRegex(SignalSnapshotLedgerConflict, "natural key"):
            repository.append_snapshot(rewritten)

    def test_get_and_list_are_read_only_and_schema_qualified(self) -> None:
        research = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        shadow = snapshot_for(ApprovalScope.SHADOW)
        connection = FakeConnection(
            [
                PostgresSignalSnapshotRepository.to_row(shadow),
                PostgresSignalSnapshotRepository.to_row(research),
            ]
        )
        repository = PostgresSignalSnapshotRepository(connection)

        self.assertEqual(repository.get_snapshot(research.snapshot_id), research)
        self.assertEqual(
            {value.snapshot_id for value in repository.list_snapshots()},
            {research.snapshot_id, shadow.snapshot_id},
        )
        selects = [query for query, _ in connection.calls if "SELECT" in query]
        self.assertTrue(all("research.signal_snapshots" in query for query in selects))
        self.assertGreaterEqual(
            sum("SET TRANSACTION READ ONLY" in query for query, _ in connection.calls),
            2,
        )

    def test_operational_and_unique_errors_fail_closed(self) -> None:
        value = snapshot_for(ApprovalScope.RESEARCH_BACKTEST)
        unavailable = PostgresSignalSnapshotRepository(
            FakeConnection(execute_error=psycopg.OperationalError("database unavailable"))
        )
        for operation in (
            lambda: unavailable.append_snapshot(value),
            lambda: unavailable.get_snapshot(value.snapshot_id),
            unavailable.list_snapshots,
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                SignalSnapshotLedgerUnavailable,
                "PostgreSQL",
            ):
                operation()

        unique = PostgresSignalSnapshotRepository(
            FakeConnection(insert_error=psycopg.errors.UniqueViolation("duplicate key"))
        )
        with self.assertRaisesRegex(SignalSnapshotLedgerConflict, "unique conflict"):
            unique.append_snapshot(value)


if __name__ == "__main__":
    unittest.main()
