import unittest
from collections.abc import Iterator
from contextlib import contextmanager

from a_share_platform.adapters.postgres.factor_reviews import (
    PostgresFactorReviewRepository,
)
from a_share_platform.application.factor_reviews import FactorReviewService
from a_share_platform.application.permissions import Principal, Role
from a_share_platform.domain.factor_lifecycle import ApprovalDecision, ApprovalScope
from tests.test_factor_lifecycle import NOW, candidate, digest, report


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

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        normalized = " ".join(query.split())
        if normalized.startswith("INSERT INTO factor_promotion_reviews"):
            self.rows.setdefault(str(params[0]), params)
            return FakeResult()
        if "FROM factor_promotion_reviews" in normalized and "WHERE review_id" in normalized:
            row = self.rows.get(str(params[0]))
            return FakeResult([] if row is None else [row])
        if "FROM factor_promotion_reviews" in normalized:
            return FakeResult([self.rows[key] for key in sorted(self.rows)])
        return FakeResult()


class PostgresFactorReviewRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = FakeConnection()

        @contextmanager
        def factory() -> Iterator[FakeConnection]:
            yield self.connection

        self.repository = PostgresFactorReviewRepository(factory)
        self.service = FactorReviewService(self.repository)

    def review(self):
        return self.service.record_review(
            factor_version=candidate(),
            validation_report=report(),
            approval_id="approval:quality:research-backtest:v1",
            scope=ApprovalScope.RESEARCH_BACKTEST,
            decision=ApprovalDecision.APPROVED,
            principal=Principal("user:reviewer-01", frozenset({Role.REVIEWER})),
            decided_at=NOW.replace(minute=5),
            reason="Reviewed the frozen evidence pack for this exact use.",
            evidence_hashes=(digest("c"),),
        )

    def test_round_trip_is_append_only_and_binds_gate_scope_lifecycle_and_actor(self) -> None:
        value = self.review()

        self.assertEqual(self.repository.get_review(value.review_id), value)
        self.assertEqual(self.repository.list_reviews(), (value,))
        insert_query, params = next(
            call for call in self.connection.calls if "INSERT INTO factor_promotion_reviews" in call[0]
        )
        self.assertIn("ON CONFLICT (review_id) DO NOTHING", insert_query)
        self.assertFalse(any("UPDATE" in query for query, _ in self.connection.calls))
        self.assertEqual(params[3], "candidate")
        self.assertTrue(params[6])
        self.assertEqual(params[7], "research_backtest")
        self.assertEqual(params[8], "approved")
        self.assertEqual(params[10], "reviewer")


if __name__ == "__main__":
    unittest.main()
