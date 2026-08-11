import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import psycopg

from a_share_platform.adapters.postgres.expected_return import (
    PostgresExpectedReturnLedgerRepository,
)
from a_share_platform.domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    ExpectedReturnCompilerV0,
    InvestmentViewOutcome,
)
from a_share_platform.domain.investment_view import InvestmentView
from a_share_platform.ports.expected_return import (
    ExpectedReturnLedgerConflict,
    ExpectedReturnLedgerUnavailable,
)
from tests.test_expected_return_compiler import DECISION_TIME, request


def json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return getattr(value, "obj", value)


def view() -> InvestmentView:
    return ExpectedReturnCompilerV0().compile(request())


def outcome(
    value: InvestmentView,
    *,
    outcome_id: str = "outcome:view:001",
) -> InvestmentViewOutcome:
    return InvestmentViewOutcome(
        outcome_id=outcome_id,
        view_id=value.view_id,
        security_id=value.security_id,
        decision_time=value.decision_time,
        horizon_trading_days=value.horizon_trading_days,
        realized_at=DECISION_TIME + timedelta(days=100),
        realized_return=Decimal("-0.03"),
        dataset_version_id="dataset:realized-return:v1",
        recorded_at=DECISION_TIME + timedelta(days=101),
    )


def calibration(
    value: InvestmentView,
    realized: InvestmentViewOutcome,
    *,
    calibration_id: str = "calibration:view:001",
) -> ExpectedReturnCalibrationRecord:
    return ExpectedReturnCalibrationRecord.from_view_and_outcome(
        calibration_id=calibration_id,
        view=value,
        outcome=realized,
        recorded_at=realized.recorded_at + timedelta(minutes=1),
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeTransaction:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeConnection:
    def __init__(self) -> None:
        self.view_rows: dict[str, tuple[object, ...]] = {}
        self.outcome_rows: dict[str, tuple[object, ...]] = {}
        self.calibration_rows: dict[str, tuple[object, ...]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.operational_error = False
        self.unique_violation_table: str | None = None

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if self.operational_error:
            raise psycopg.OperationalError("database unavailable")
        normalized = " ".join(query.split())
        inserts = {
            "research.investment_views": self.view_rows,
            "research.investment_view_outcomes": self.outcome_rows,
            "research.expected_return_calibrations": self.calibration_rows,
        }
        for table, insert_rows in inserts.items():
            if normalized.startswith(f"INSERT INTO {table}"):
                if self.unique_violation_table == table:
                    raise psycopg.errors.UniqueViolation("immutable unique conflict")
                insert_rows.setdefault(str(params[0]), params)
                return FakeResult()
        if "FROM research.investment_views" in normalized:
            if "WHERE view_id" in normalized:
                row = self.view_rows.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            return FakeResult([self.view_rows[key] for key in sorted(self.view_rows)])
        if "FROM research.investment_view_outcomes" in normalized:
            if "WHERE outcome_id" in normalized:
                row = self.outcome_rows.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            if "WHERE view_id" in normalized:
                selected_rows = [row for row in self.outcome_rows.values() if row[2] == params[0]]
                return FakeResult(selected_rows)
            return FakeResult([self.outcome_rows[key] for key in sorted(self.outcome_rows)])
        if "FROM research.expected_return_calibrations" in normalized:
            if "WHERE calibration_id" in normalized:
                row = self.calibration_rows.get(str(params[0]))
                return FakeResult([] if row is None else [row])
            if "WHERE outcome_id" in normalized:
                selected_rows = [
                    row for row in self.calibration_rows.values() if row[3] == params[0]
                ]
                return FakeResult(selected_rows)
            return FakeResult([self.calibration_rows[key] for key in sorted(self.calibration_rows)])
        return FakeResult()


class PostgresExpectedReturnLedgerRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()

        @contextmanager
        def factory() -> Iterator[FakeConnection]:
            yield self.connection

        self.repository = PostgresExpectedReturnLedgerRepository(factory)
        self.view = view()
        self.outcome = outcome(self.view)
        self.calibration = calibration(self.view, self.outcome)

    def test_jsonb_round_trip_uses_research_tables_and_preserves_complete_records(self) -> None:
        self.assertEqual(self.repository.append_view(self.view), self.view)
        self.assertEqual(self.repository.append_outcome(self.outcome), self.outcome)
        self.assertEqual(
            self.repository.append_calibration(self.calibration),
            self.calibration,
        )

        self.assertEqual(self.repository.get_view(self.view.view_id), self.view)
        self.assertEqual(self.repository.get_outcome(self.outcome.outcome_id), self.outcome)
        self.assertEqual(
            self.repository.get_calibration(self.calibration.calibration_id),
            self.calibration,
        )
        self.assertEqual(self.repository.list_views(), (self.view,))
        self.assertEqual(self.repository.list_outcomes(), (self.outcome,))
        self.assertEqual(self.repository.list_calibrations(), (self.calibration,))
        self.assertEqual(self.repository.outcome_for_view(self.view.view_id), self.outcome)
        self.assertEqual(
            self.repository.calibration_for_outcome(self.outcome.outcome_id),
            self.calibration,
        )

        view_insert = next(
            call
            for call in self.connection.calls
            if "INSERT INTO research.investment_views" in call[0]
        )
        outcome_insert = next(
            call
            for call in self.connection.calls
            if "INSERT INTO research.investment_view_outcomes" in call[0]
        )
        calibration_insert = next(
            call
            for call in self.connection.calls
            if "INSERT INTO research.expected_return_calibrations" in call[0]
        )
        self.assertEqual(json_value(view_insert[1][11]), self.view.hash_payload())
        self.assertEqual(json_value(outcome_insert[1][8]), self.outcome.hash_payload())
        self.assertEqual(
            json_value(calibration_insert[1][4]),
            self.calibration.hash_payload(),
        )
        self.assertIn("ON CONFLICT (view_id) DO NOTHING", view_insert[0])
        self.assertIn("ON CONFLICT (outcome_id) DO NOTHING", outcome_insert[0])
        self.assertIn("ON CONFLICT (calibration_id) DO NOTHING", calibration_insert[0])
        self.assertFalse(any("UPDATE" in query for query, _ in self.connection.calls))
        self.assertTrue(
            any("SET TRANSACTION READ ONLY" in query for query, _ in self.connection.calls)
        )

    def test_same_identifiers_and_content_are_idempotent_without_second_insert(self) -> None:
        self.assertEqual(self.repository.append_view(self.view), self.view)
        self.assertEqual(self.repository.append_view(self.view), self.view)
        self.assertEqual(self.repository.append_outcome(self.outcome), self.outcome)
        self.assertEqual(self.repository.append_outcome(self.outcome), self.outcome)
        self.assertEqual(
            self.repository.append_calibration(self.calibration),
            self.calibration,
        )
        self.assertEqual(
            self.repository.append_calibration(self.calibration),
            self.calibration,
        )
        for table in (
            "research.investment_views",
            "research.investment_view_outcomes",
            "research.expected_return_calibrations",
        ):
            inserts = [
                query
                for query, _ in self.connection.calls
                if query.lstrip().startswith(f"INSERT INTO {table}")
            ]
            self.assertEqual(len(inserts), 1)

    def test_same_identifier_with_different_content_fails_closed(self) -> None:
        self.repository.append_view(self.view)
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "InvestmentView"):
            self.repository.append_view(replace(self.view, catalysts=("different catalyst",)))

        self.repository.append_outcome(self.outcome)
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "outcome"):
            self.repository.append_outcome(replace(self.outcome, realized_return=Decimal("0.25")))

        self.repository.append_calibration(self.calibration)
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "Calibration"):
            self.repository.append_calibration(
                replace(
                    self.calibration,
                    recorded_at=self.calibration.recorded_at + timedelta(minutes=1),
                )
            )

    def test_only_one_outcome_per_view_and_one_calibration_per_outcome(self) -> None:
        self.repository.append_view(self.view)
        self.repository.append_outcome(self.outcome)
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "outcome.*view"):
            self.repository.append_outcome(replace(self.outcome, outcome_id="outcome:view:second"))

        self.repository.append_calibration(self.calibration)
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "Calibration.*outcome"):
            self.repository.append_calibration(
                replace(self.calibration, calibration_id="calibration:view:second")
            )

    def test_stored_hash_mismatch_is_rejected_for_every_document_type(self) -> None:
        self.repository.append_view(self.view)
        self.repository.append_outcome(self.outcome)
        self.repository.append_calibration(self.calibration)
        cases = (
            (self.connection.view_rows, self.view.view_id, self.repository.get_view),
            (
                self.connection.outcome_rows,
                self.outcome.outcome_id,
                self.repository.get_outcome,
            ),
            (
                self.connection.calibration_rows,
                self.calibration.calibration_id,
                self.repository.get_calibration,
            ),
        )
        for rows, identifier, getter in cases:
            original = rows[identifier]
            rows[identifier] = (original[0], "0" * 64, *original[2:])
            with (
                self.subTest(identifier=identifier),
                self.assertRaisesRegex(
                    ValueError,
                    "hash mismatch",
                ),
            ):
                getter(identifier)
            rows[identifier] = original

    def test_operational_error_is_translated_to_unavailable_for_writes_and_reads(self) -> None:
        self.connection.operational_error = True
        with self.assertRaisesRegex(ExpectedReturnLedgerUnavailable, "PostgreSQL"):
            self.repository.append_view(self.view)
        with self.assertRaisesRegex(ExpectedReturnLedgerUnavailable, "PostgreSQL"):
            self.repository.list_views()

    def test_unique_violation_is_translated_to_immutable_conflict_for_each_table(self) -> None:
        self.connection.unique_violation_table = "research.investment_views"
        with self.assertRaises(ExpectedReturnLedgerConflict):
            self.repository.append_view(self.view)
        self.connection.unique_violation_table = "research.investment_view_outcomes"
        with self.assertRaises(ExpectedReturnLedgerConflict):
            self.repository.append_outcome(self.outcome)
        self.connection.unique_violation_table = "research.expected_return_calibrations"
        with self.assertRaises(ExpectedReturnLedgerConflict):
            self.repository.append_calibration(self.calibration)


if __name__ == "__main__":
    unittest.main()
