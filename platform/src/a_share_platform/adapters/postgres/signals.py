"""PostgreSQL adapter for immutable, approval-scoped SignalSnapshots."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast

import psycopg

from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.domain.signals import SignalSnapshot
from a_share_platform.ports.signals import (
    SignalSnapshotLedgerConflict,
    SignalSnapshotLedgerUnavailable,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return getattr(value, "obj", value)


def _mapping(value: object, field_name: str) -> Mapping[object, object]:
    parsed = _json_value(value)
    if not isinstance(parsed, Mapping):
        raise TypeError(f"stored {field_name} must be an object")
    return parsed


def _array(value: object, field_name: str) -> Sequence[object]:
    parsed = _json_value(value)
    if not isinstance(parsed, (list, tuple)):
        raise TypeError(f"stored {field_name} must be an array")
    return parsed


def _required(document: Mapping[object, object], name: str) -> object:
    if name not in document:
        raise ValueError(f"stored SignalSnapshot document is missing {name}")
    return document[name]


def _datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO datetime") from error


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"stored {field_name} must be an integer")
    try:
        return int(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an integer") from error


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    items = _array(value, field_name)
    if any(not isinstance(item, str) for item in items):
        raise TypeError(f"stored {field_name} must contain strings")
    return tuple(cast(str, item) for item in items)


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


class PostgresSignalSnapshotRepository:
    """One transaction per operation; the DSN is never retained or exposed."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresSignalSnapshotRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(append_only=True)"

    def append_snapshot(self, value: SignalSnapshot) -> SignalSnapshot:
        if not isinstance(value, SignalSnapshot):
            raise TypeError("value must be a SignalSnapshot")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._get_snapshot(connection, value.snapshot_id)
                if existing is not None:
                    if existing.content_hash != value.content_hash:
                        raise SignalSnapshotLedgerConflict(
                            f"immutable snapshot_id conflict: {value.snapshot_id}"
                        )
                    return existing
                natural = self._get_by_natural_key(connection, value)
                if natural is not None:
                    raise SignalSnapshotLedgerConflict(
                        "SignalSnapshot natural key is immutable; "
                        f"existing={natural.snapshot_id}; attempted={value.snapshot_id}"
                    )
                row = self.to_row(value)
                connection.execute(
                    """
                    INSERT INTO research.signal_snapshots (
                        snapshot_id, content_hash, security_id, decision_time,
                        horizon_trading_days, universe_version_id, rank,
                        universe_size, investment_view_id, investment_view_hash,
                        approval_scope, data_mode, deployment_stage, trust_state,
                        data_cutoff, factor_version_ids, factor_review_ids,
                        snapshot_document, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (snapshot_id) DO NOTHING
                    """,
                    (
                        *row[:15],
                        _json_parameter(row[15]),
                        _json_parameter(row[16]),
                        _json_parameter(row[17]),
                        row[18],
                    ),
                )
                stored = self._get_snapshot(connection, value.snapshot_id)
                if stored is None:
                    raise RuntimeError("SignalSnapshot insert was not observable")
                if stored.content_hash != value.content_hash:
                    raise SignalSnapshotLedgerConflict(
                        f"immutable snapshot_id conflict: {value.snapshot_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise SignalSnapshotLedgerUnavailable(
                "PostgreSQL SignalSnapshot store is unavailable"
            ) from error
        except psycopg.errors.UniqueViolation as error:
            raise SignalSnapshotLedgerConflict(
                f"SignalSnapshot unique conflict: {value.snapshot_id}"
            ) from error

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_snapshot(connection, snapshot_id)
        except psycopg.OperationalError as error:
            raise SignalSnapshotLedgerUnavailable(
                "PostgreSQL SignalSnapshot store is unavailable"
            ) from error

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    self._select() + " ORDER BY snapshot_id"
                ).fetchall()
                return tuple(self._from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise SignalSnapshotLedgerUnavailable(
                "PostgreSQL SignalSnapshot store is unavailable"
            ) from error

    def _get_snapshot(
        self,
        connection: Connection,
        snapshot_id: str,
    ) -> SignalSnapshot | None:
        row = connection.execute(
            self._select() + " WHERE snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    def _get_by_natural_key(
        self,
        connection: Connection,
        value: SignalSnapshot,
    ) -> SignalSnapshot | None:
        row = connection.execute(
            self._select()
            + """
              WHERE universe_version_id = %s
                AND security_id = %s
                AND decision_time = %s
                AND horizon_trading_days = %s
                AND approval_scope = %s
            """,
            (
                value.universe_version_id,
                value.security_id,
                value.decision_time,
                value.horizon_trading_days,
                value.approval_scope.value,
            ),
        ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _select() -> str:
        return """
            SELECT snapshot_id, content_hash, security_id, decision_time,
                   horizon_trading_days, universe_version_id, rank,
                   universe_size, investment_view_id, investment_view_hash,
                   approval_scope, data_mode, deployment_stage, trust_state,
                   data_cutoff, factor_version_ids, factor_review_ids,
                   snapshot_document, created_at
            FROM research.signal_snapshots
        """

    @staticmethod
    def to_row(value: SignalSnapshot) -> tuple[object, ...]:
        if not isinstance(value, SignalSnapshot):
            raise TypeError("value must be a SignalSnapshot")
        return (
            value.snapshot_id,
            value.content_hash,
            value.security_id,
            value.decision_time,
            value.horizon_trading_days,
            value.universe_version_id,
            value.rank,
            value.universe_size,
            value.investment_view_id,
            value.investment_view_hash,
            value.approval_scope.value,
            value.run_context.data_mode.value,
            value.run_context.deployment_stage.value,
            value.trust_state.value,
            value.data_cutoff,
            list(value.factor_version_ids),
            list(value.factor_review_ids),
            value.hash_payload(),
            value.created_at,
        )

    @staticmethod
    def _from_row(row: Sequence[object]) -> SignalSnapshot:
        if len(row) != 19:
            raise ValueError("stored SignalSnapshot row must contain 19 columns")
        document = _mapping(row[17], "snapshot_document")
        context = _mapping(_required(document, "run_context"), "run_context")
        value = SignalSnapshot(
            snapshot_id=str(_required(document, "snapshot_id")),
            security_id=str(_required(document, "security_id")),
            decision_time=_datetime(
                _required(document, "decision_time"),
                "decision_time",
            ),
            horizon_trading_days=_integer(
                _required(document, "horizon_trading_days"),
                "horizon_trading_days",
            ),
            universe_version_id=str(_required(document, "universe_version_id")),
            universe_size=_integer(_required(document, "universe_size"), "universe_size"),
            rank=_integer(_required(document, "rank"), "rank"),
            previous_rank=(
                None
                if _required(document, "previous_rank") is None
                else _integer(_required(document, "previous_rank"), "previous_rank")
            ),
            score=Decimal(str(_required(document, "score"))),
            expected_return=Decimal(str(_required(document, "expected_return"))),
            confidence=Decimal(str(_required(document, "confidence"))),
            investment_view_id=str(_required(document, "investment_view_id")),
            investment_view_hash=str(_required(document, "investment_view_hash")),
            factor_version_ids=_strings(
                _required(document, "factor_version_ids"),
                "factor_version_ids",
            ),
            factor_version_hashes=_strings(
                _required(document, "factor_version_hashes"),
                "factor_version_hashes",
            ),
            factor_review_ids=_strings(
                _required(document, "factor_review_ids"),
                "factor_review_ids",
            ),
            factor_review_hashes=_strings(
                _required(document, "factor_review_hashes"),
                "factor_review_hashes",
            ),
            dataset_version_ids=_strings(
                _required(document, "dataset_version_ids"),
                "dataset_version_ids",
            ),
            feature_version_ids=_strings(
                _required(document, "feature_version_ids"),
                "feature_version_ids",
            ),
            model_version_id=str(_required(document, "model_version_id")),
            run_id=str(_required(document, "run_id")),
            approval_scope=ApprovalScope(str(_required(document, "approval_scope"))),
            run_context=RunContext(
                DataMode(str(_required(context, "data_mode"))),
                DeploymentStage(str(_required(context, "deployment_stage"))),
            ),
            trust_state=DataTrustState(str(_required(document, "trust_state"))),
            data_cutoff=_datetime(_required(document, "data_cutoff"), "data_cutoff"),
            created_at=_datetime(_required(document, "created_at"), "created_at"),
        )
        indexed = (
            str(row[0]),
            str(row[2]),
            _datetime(row[3], "indexed decision_time"),
            _integer(row[4], "indexed horizon_trading_days"),
            str(row[5]),
            _integer(row[6], "indexed rank"),
            _integer(row[7], "indexed universe_size"),
            str(row[8]),
            str(row[9]),
            str(row[10]),
            str(row[11]),
            str(row[12]),
            str(row[13]),
            _datetime(row[14], "indexed data_cutoff"),
            _strings(row[15], "indexed factor_version_ids"),
            _strings(row[16], "indexed factor_review_ids"),
            _datetime(row[18], "indexed created_at"),
        )
        expected = (
            value.snapshot_id,
            value.security_id,
            value.decision_time,
            value.horizon_trading_days,
            value.universe_version_id,
            value.rank,
            value.universe_size,
            value.investment_view_id,
            value.investment_view_hash,
            value.approval_scope.value,
            value.run_context.data_mode.value,
            value.run_context.deployment_stage.value,
            value.trust_state.value,
            value.data_cutoff,
            value.factor_version_ids,
            value.factor_review_ids,
            value.created_at,
        )
        if indexed != expected:
            raise ValueError(f"stored SignalSnapshot indexed fields mismatch: {value.snapshot_id}")
        if value.content_hash != str(row[1]):
            raise ValueError(f"stored SignalSnapshot hash mismatch: {value.snapshot_id}")
        return value


__all__ = ["PostgresSignalSnapshotRepository"]
