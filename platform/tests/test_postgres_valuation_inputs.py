import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

import psycopg

from a_share_platform.adapters.postgres.valuation_inputs import (
    PostgresValuationImprovementInputRepository,
)
from a_share_platform.ports.valuation_inputs import (
    ValuationImprovementInputConflict,
    ValuationImprovementInputUnavailable,
)
from tests.test_valuation_improvement_service import bundle, request


def json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return getattr(value, "obj", value)


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
        self.rows: dict[str, tuple[object, ...]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.operational_error = False
        self.unique_violation = False

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        if self.operational_error:
            raise psycopg.OperationalError("database unavailable")
        normalized = " ".join(query.split())
        if normalized.startswith("INSERT INTO research.valuation_input_bundles"):
            if self.unique_violation:
                raise psycopg.errors.UniqueViolation("immutable unique conflict")
            self.rows.setdefault(str(params[0]), params)
            return FakeResult()
        if "FROM research.valuation_input_bundles" in normalized:
            row = self.rows.get(str(params[4]))
            if row is None:
                return FakeResult()
            if (
                row[1] != params[0]
                or row[2] != params[1]
                or row[4] != params[2]
                or row[5] != params[3]
            ):
                return FakeResult()
            return FakeResult([row])
        return FakeResult()


class PostgresValuationImprovementInputRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()

        @contextmanager
        def factory() -> Iterator[FakeConnection]:
            yield self.connection

        self.repository = PostgresValuationImprovementInputRepository(factory)
        self.value = bundle()

    def test_append_then_exact_key_load_round_trips_complete_frozen_bundle(self) -> None:
        self.assertEqual(self.repository.append(self.value), self.value)
        self.assertEqual(self.repository.load(request()), self.value)

        insert = next(
            call
            for call in self.connection.calls
            if "INSERT INTO research.valuation_input_bundles" in call[0]
        )
        self.assertEqual(insert[1][0], self.value.bundle_version_id)
        self.assertEqual(insert[1][1], self.value.security_id)
        self.assertEqual(insert[1][2], self.value.decision_time)
        self.assertEqual(insert[1][4], self.value.data_mode.value)
        self.assertEqual(insert[1][5], self.value.trust_state.value)
        self.assertEqual(
            json_value(insert[1][7]),
            sorted(self.value.dataset_version_ids),
        )
        self.assertIsInstance(json_value(insert[1][8]), dict)
        self.assertIn("ON CONFLICT (bundle_version_id) DO NOTHING", insert[0])
        self.assertFalse(any("UPDATE" in query for query, _ in self.connection.calls))
        self.assertTrue(
            any("SET TRANSACTION READ ONLY" in query for query, _ in self.connection.calls)
        )

    def test_append_is_idempotent_and_same_identifier_with_other_content_conflicts(self) -> None:
        self.assertEqual(self.repository.append(self.value), self.value)
        self.assertEqual(self.repository.append(self.value), self.value)
        inserts = [
            query
            for query, _ in self.connection.calls
            if query.lstrip().startswith("INSERT INTO research.valuation_input_bundles")
        ]
        self.assertEqual(len(inserts), 1)

        changed = replace(self.value, comparable_set_version_id="comparable-set:other:v1")
        with self.assertRaisesRegex(ValuationImprovementInputConflict, "immutable"):
            self.repository.append(changed)

    def test_exact_key_mismatch_returns_none_and_stored_hash_tampering_fails_closed(self) -> None:
        self.repository.append(self.value)
        self.assertIsNone(
            self.repository.load(
                replace(request(), bundle_version_id="bundle:security:missing:v1")
            )
        )

        row = self.connection.rows[self.value.bundle_version_id]
        self.connection.rows[self.value.bundle_version_id] = (
            row[0],
            row[1],
            row[2],
            "0" * 64,
            *row[4:],
        )
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.repository.load(request())

    def test_database_failures_are_translated_without_fixture_fallback(self) -> None:
        self.connection.operational_error = True
        with self.assertRaisesRegex(ValuationImprovementInputUnavailable, "PostgreSQL"):
            self.repository.append(self.value)
        with self.assertRaisesRegex(ValuationImprovementInputUnavailable, "PostgreSQL"):
            self.repository.load(request())

        self.connection.operational_error = False
        self.connection.unique_violation = True
        with self.assertRaisesRegex(ValuationImprovementInputConflict, "immutable"):
            self.repository.append(self.value)


if __name__ == "__main__":
    unittest.main()
