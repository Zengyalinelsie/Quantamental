"""PostgreSQL adapter for append-only factor promotion review records."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol, cast

import psycopg

from a_share_platform.domain.factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorLifecycleStatus,
    PromotionApproval,
)
from a_share_platform.domain.factor_reviews import (
    FactorPromotionReview,
    FactorReviewConflict,
)
from a_share_platform.ports.factor_reviews import FactorReviewStoreUnavailable


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _array(value: object, field_name: str) -> Sequence[object]:
    parsed = json.loads(value) if isinstance(value, str) else getattr(value, "obj", value)
    if not isinstance(parsed, (list, tuple)):
        raise TypeError(f"stored {field_name} must be an array")
    return parsed


def _datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO datetime") from error


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...

    def fetchall(self) -> list[tuple[object, ...]]: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


class PostgresFactorReviewRepository:
    """Persist review evidence without exposing or retaining the DSN."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresFactorReviewRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(append_only=True)"

    def save_review(self, value: FactorPromotionReview) -> FactorPromotionReview:
        if not isinstance(value, FactorPromotionReview):
            raise TypeError("value must be a FactorPromotionReview")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._get_review(connection, value.review_id)
                if existing is not None:
                    if existing != value:
                        raise FactorReviewConflict(
                            f"immutable factor review conflict: {value.review_id}"
                        )
                    return existing
                row = self.to_row(value)
                connection.execute(
                    """
                    INSERT INTO factor_promotion_reviews (
                        review_id, content_hash, factor_version_id,
                        factor_lifecycle_status, factor_version_hash,
                        validation_report_id, scientific_gate_passed, scope,
                        decision, reviewer_id, reviewer_role,
                        validation_report_hash, decided_at, reason, evidence_hashes
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (review_id) DO NOTHING
                    """,
                    (*row[:-1], _json_parameter(row[-1])),
                )
                stored = self._get_review(connection, value.review_id)
                if stored is None:
                    raise RuntimeError("factor review insert was not observable")
                if stored != value:
                    raise FactorReviewConflict(
                        f"immutable factor review conflict: {value.review_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise FactorReviewStoreUnavailable(
                "PostgreSQL factor review store is unavailable"
            ) from error
        except psycopg.errors.UniqueViolation as error:
            raise FactorReviewConflict(
                f"immutable factor review content conflict: {value.review_id}"
            ) from error

    def get_review(self, review_id: str) -> FactorPromotionReview | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_review(connection, review_id)
        except psycopg.OperationalError as error:
            raise FactorReviewStoreUnavailable(
                "PostgreSQL factor review store is unavailable"
            ) from error

    def list_reviews(self) -> tuple[FactorPromotionReview, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(self._select() + " ORDER BY review_id").fetchall()
                return tuple(self._from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise FactorReviewStoreUnavailable(
                "PostgreSQL factor review store is unavailable"
            ) from error

    def _get_review(
        self,
        connection: Connection,
        review_id: str,
    ) -> FactorPromotionReview | None:
        row = connection.execute(
            self._select() + " WHERE review_id = %s",
            (review_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _select() -> str:
        return """
            SELECT review_id, content_hash, factor_version_id,
                   factor_lifecycle_status, factor_version_hash,
                   validation_report_id, scientific_gate_passed, scope,
                   decision, reviewer_id, reviewer_role,
                   validation_report_hash, decided_at, reason, evidence_hashes
            FROM factor_promotion_reviews
        """

    @staticmethod
    def to_row(value: FactorPromotionReview) -> tuple[object, ...]:
        approval = value.approval
        return (
            value.review_id,
            value.content_hash,
            value.factor_version_id,
            value.factor_lifecycle_status.value,
            value.factor_version_hash,
            value.validation_report_id,
            value.scientific_gate_passed,
            approval.scope.value,
            approval.decision.value,
            approval.actor_id,
            approval.actor_role,
            value.validation_report_hash,
            approval.decided_at,
            approval.reason,
            list(approval.evidence_hashes),
        )

    @staticmethod
    def _from_row(row: Sequence[object]) -> FactorPromotionReview:
        evidence_hashes = tuple(str(item) for item in _array(row[14], "evidence_hashes"))
        approval = PromotionApproval(
            approval_id=str(row[0]),
            factor_version_id=str(row[2]),
            validation_report_id=str(row[5]),
            validation_report_hash=str(row[11]),
            scope=ApprovalScope(str(row[7])),
            decision=ApprovalDecision(str(row[8])),
            actor_id=str(row[9]),
            actor_role=str(row[10]),
            decided_at=_datetime(row[12], "decided_at"),
            reason=str(row[13]),
            evidence_hashes=evidence_hashes,
        )
        value = FactorPromotionReview(
            review_id=str(row[0]),
            factor_version_id=str(row[2]),
            factor_version_hash=str(row[4]),
            factor_lifecycle_status=FactorLifecycleStatus(str(row[3])),
            validation_report_id=str(row[5]),
            validation_report_hash=str(row[11]),
            scientific_gate_passed=cast(bool, row[6]),
            approval=approval,
        )
        if value.content_hash != str(row[1]):
            raise ValueError(f"stored factor review hash mismatch: {value.review_id}")
        return value


__all__ = ["PostgresFactorReviewRepository"]
