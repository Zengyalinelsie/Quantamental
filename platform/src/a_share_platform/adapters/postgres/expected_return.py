"""PostgreSQL adapter for immutable Expected Return ledger records."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import datetime
from decimal import Decimal
from typing import Protocol, cast

import psycopg

from a_share_platform.domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    InvestmentViewOutcome,
)
from a_share_platform.domain.investment_view import (
    ExpectedReturnDistribution,
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.expected_return import (
    ExpectedReturnLedgerConflict,
    ExpectedReturnLedgerUnavailable,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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
        raise ValueError(f"stored Expected Return document is missing {name}")
    return document[name]


def _datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    encoded = str(value)
    if encoded.endswith("Z"):
        encoded = encoded[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(encoded)
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO datetime") from error


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as error:
        raise ValueError(f"stored {field_name} is not a Decimal") from error


def _integer(value: object, field_name: str) -> int:
    if type(value) is int:
        return cast(int, value)
    try:
        return int(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an integer") from error


def _boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"stored {field_name} must be a boolean")
    return cast(bool, value)


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


class PostgresExpectedReturnLedgerRepository:
    """Append-only InvestmentView, outcome, and calibration repository."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresExpectedReturnLedgerRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(append_only=True)"

    def append_view(self, value: InvestmentView) -> InvestmentView:
        if not isinstance(value, InvestmentView):
            raise TypeError("value must be an InvestmentView")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._get_view(connection, value.view_id)
                if existing is not None:
                    if existing.content_hash != value.content_hash:
                        raise ExpectedReturnLedgerConflict(
                            f"immutable InvestmentView conflict: {value.view_id}"
                        )
                    return existing
                row = self.to_view_row(value)
                connection.execute(
                    """
                    INSERT INTO research.investment_views (
                        view_id, content_hash, security_id, decision_time,
                        horizon_trading_days, data_mode, deployment_stage,
                        trust_state, data_cutoff, model_version_id, run_id,
                        view_document
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (view_id) DO NOTHING
                    """,
                    (*row[:-1], _json_parameter(row[-1])),
                )
                stored = self._get_view(connection, value.view_id)
                if stored is None:
                    raise RuntimeError("InvestmentView insert was not observable")
                if stored.content_hash != value.content_hash:
                    raise ExpectedReturnLedgerConflict(
                        f"immutable InvestmentView conflict: {value.view_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise ExpectedReturnLedgerConflict(
                f"immutable InvestmentView content conflict: {value.view_id}"
            ) from error

    def get_view(self, view_id: str) -> InvestmentView | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_view(connection, view_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_views(self) -> tuple[InvestmentView, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(self._view_select() + " ORDER BY view_id").fetchall()
                return tuple(self._view_from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def append_outcome(self, value: InvestmentViewOutcome) -> InvestmentViewOutcome:
        if not isinstance(value, InvestmentViewOutcome):
            raise TypeError("value must be an InvestmentViewOutcome")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._get_outcome(connection, value.outcome_id)
                if existing is not None:
                    if existing.content_hash != value.content_hash:
                        raise ExpectedReturnLedgerConflict(
                            f"immutable InvestmentView outcome conflict: {value.outcome_id}"
                        )
                    return existing
                prior = self._outcome_for_view(connection, value.view_id)
                if prior is not None:
                    raise ExpectedReturnLedgerConflict(
                        f"outcome for view {value.view_id} is immutable; "
                        f"existing={prior.outcome_id}"
                    )
                row = self.to_outcome_row(value)
                connection.execute(
                    """
                    INSERT INTO research.investment_view_outcomes (
                        outcome_id, content_hash, view_id, security_id,
                        decision_time, horizon_trading_days, realized_at,
                        dataset_version_id, source_policy_version,
                        source_available_at, outcome_document, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (outcome_id) DO NOTHING
                    """,
                    (*row[:10], _json_parameter(row[10]), row[11]),
                )
                stored = self._get_outcome(connection, value.outcome_id)
                if stored is None:
                    raise RuntimeError("InvestmentView outcome insert was not observable")
                if stored.content_hash != value.content_hash:
                    raise ExpectedReturnLedgerConflict(
                        f"immutable InvestmentView outcome conflict: {value.outcome_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise ExpectedReturnLedgerConflict(
                f"immutable outcome conflict: {value.outcome_id} / view={value.view_id}"
            ) from error

    def get_outcome(self, outcome_id: str) -> InvestmentViewOutcome | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_outcome(connection, outcome_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def outcome_for_view(self, view_id: str) -> InvestmentViewOutcome | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._outcome_for_view(connection, view_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_outcomes(self) -> tuple[InvestmentViewOutcome, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    self._outcome_select() + " ORDER BY outcome_id"
                ).fetchall()
                return tuple(self._outcome_from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def append_calibration(
        self,
        value: ExpectedReturnCalibrationRecord,
    ) -> ExpectedReturnCalibrationRecord:
        if not isinstance(value, ExpectedReturnCalibrationRecord):
            raise TypeError("value must be an ExpectedReturnCalibrationRecord")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._get_calibration(connection, value.calibration_id)
                if existing is not None:
                    if existing.content_hash != value.content_hash:
                        raise ExpectedReturnLedgerConflict(
                            f"immutable Calibration conflict: {value.calibration_id}"
                        )
                    return existing
                prior = self._calibration_for_outcome(connection, value.outcome_id)
                if prior is not None:
                    raise ExpectedReturnLedgerConflict(
                        f"Calibration for outcome {value.outcome_id} already exists: "
                        f"{prior.calibration_id}"
                    )
                row = self.to_calibration_row(value)
                connection.execute(
                    """
                    INSERT INTO research.expected_return_calibrations (
                        calibration_id, content_hash, view_id, outcome_id,
                        calibration_document, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (calibration_id) DO NOTHING
                    """,
                    (*row[:4], _json_parameter(row[4]), row[5]),
                )
                stored = self._get_calibration(connection, value.calibration_id)
                if stored is None:
                    raise RuntimeError("Expected Return calibration insert was not observable")
                if stored.content_hash != value.content_hash:
                    raise ExpectedReturnLedgerConflict(
                        f"immutable Calibration conflict: {value.calibration_id}"
                    )
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise ExpectedReturnLedgerConflict(
                f"immutable Calibration conflict: {value.calibration_id} / "
                f"outcome={value.outcome_id}"
            ) from error

    def get_calibration(
        self,
        calibration_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._get_calibration(connection, calibration_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def calibration_for_outcome(
        self,
        outcome_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._calibration_for_outcome(connection, outcome_id)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    def list_calibrations(self) -> tuple[ExpectedReturnCalibrationRecord, ...]:
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    self._calibration_select() + " ORDER BY calibration_id"
                ).fetchall()
                return tuple(self._calibration_from_row(row) for row in rows)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    @staticmethod
    def _unavailable() -> ExpectedReturnLedgerUnavailable:
        return ExpectedReturnLedgerUnavailable("PostgreSQL Expected Return ledger is unavailable")

    @staticmethod
    def _view_select() -> str:
        return """
            SELECT view_id, content_hash, security_id, decision_time,
                   horizon_trading_days, data_mode, deployment_stage,
                   trust_state, data_cutoff, model_version_id, run_id,
                   view_document
            FROM research.investment_views
        """

    @staticmethod
    def _outcome_select() -> str:
        return """
            SELECT outcome_id, content_hash, view_id, security_id,
                   decision_time, horizon_trading_days, realized_at,
                   dataset_version_id, source_policy_version,
                   source_available_at, outcome_document, recorded_at
            FROM research.investment_view_outcomes
        """

    @staticmethod
    def _calibration_select() -> str:
        return """
            SELECT calibration_id, content_hash, view_id, outcome_id,
                   calibration_document, recorded_at
            FROM research.expected_return_calibrations
        """

    def _get_view(self, connection: Connection, view_id: str) -> InvestmentView | None:
        row = connection.execute(
            self._view_select() + " WHERE view_id = %s",
            (view_id,),
        ).fetchone()
        return None if row is None else self._view_from_row(row)

    def _get_outcome(
        self,
        connection: Connection,
        outcome_id: str,
    ) -> InvestmentViewOutcome | None:
        row = connection.execute(
            self._outcome_select() + " WHERE outcome_id = %s",
            (outcome_id,),
        ).fetchone()
        return None if row is None else self._outcome_from_row(row)

    def _outcome_for_view(
        self,
        connection: Connection,
        view_id: str,
    ) -> InvestmentViewOutcome | None:
        row = connection.execute(
            self._outcome_select() + " WHERE view_id = %s",
            (view_id,),
        ).fetchone()
        return None if row is None else self._outcome_from_row(row)

    def _get_calibration(
        self,
        connection: Connection,
        calibration_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        row = connection.execute(
            self._calibration_select() + " WHERE calibration_id = %s",
            (calibration_id,),
        ).fetchone()
        return None if row is None else self._calibration_from_row(row)

    def _calibration_for_outcome(
        self,
        connection: Connection,
        outcome_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        row = connection.execute(
            self._calibration_select() + " WHERE outcome_id = %s",
            (outcome_id,),
        ).fetchone()
        return None if row is None else self._calibration_from_row(row)

    @staticmethod
    def to_view_row(value: InvestmentView) -> tuple[object, ...]:
        return (
            value.view_id,
            value.content_hash,
            value.security_id,
            value.decision_time,
            value.horizon_trading_days,
            value.run_context.data_mode.value,
            value.run_context.deployment_stage.value,
            value.trust_state.value,
            value.latest_input_available_at,
            value.model_version_id,
            value.run_id,
            value.hash_payload(),
        )

    @staticmethod
    def to_outcome_row(value: InvestmentViewOutcome) -> tuple[object, ...]:
        return (
            value.outcome_id,
            value.content_hash,
            value.view_id,
            value.security_id,
            value.decision_time,
            value.horizon_trading_days,
            value.realized_at,
            value.dataset_version_id,
            value.source_policy_version,
            value.source_available_at,
            value.hash_payload(),
            value.recorded_at,
        )

    @staticmethod
    def to_calibration_row(value: ExpectedReturnCalibrationRecord) -> tuple[object, ...]:
        return (
            value.calibration_id,
            value.content_hash,
            value.view_id,
            value.outcome_id,
            value.hash_payload(),
            value.recorded_at,
        )

    @staticmethod
    def _view_from_row(row: Sequence[object]) -> InvestmentView:
        document = _mapping(row[11], "view_document")
        expected_return = _mapping(
            _required(document, "expected_return"),
            "expected_return",
        )
        components = tuple(
            PostgresExpectedReturnLedgerRepository._component_from_document(
                _mapping(item, "component")
            )
            for item in _array(_required(document, "components"), "components")
        )
        context = _mapping(_required(document, "run_context"), "run_context")
        value = InvestmentView(
            view_id=str(_required(document, "view_id")),
            security_id=str(_required(document, "security_id")),
            decision_time=_datetime(
                _required(document, "decision_time"),
                "decision_time",
            ),
            horizon_trading_days=_integer(
                _required(document, "horizon_trading_days"),
                "horizon_trading_days",
            ),
            expected_return=ExpectedReturnDistribution(
                point=_decimal(_required(expected_return, "point"), "point"),
                p10=_decimal(_required(expected_return, "p10"), "p10"),
                p50=_decimal(_required(expected_return, "p50"), "p50"),
                p90=_decimal(_required(expected_return, "p90"), "p90"),
                downside=_decimal(
                    _required(expected_return, "downside"),
                    "downside",
                ),
            ),
            confidence=_decimal(_required(document, "confidence"), "confidence"),
            components=components,
            residual=_decimal(_required(document, "residual"), "residual"),
            residual_reason=str(_required(document, "residual_reason")),
            residual_evidence_ids=_strings(
                _required(document, "residual_evidence_ids"),
                "residual_evidence_ids",
            ),
            catalysts=_strings(_required(document, "catalysts"), "catalysts"),
            invalidators=_strings(
                _required(document, "invalidators"),
                "invalidators",
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
            code_version=str(_required(document, "code_version")),
            environment_id=str(_required(document, "environment_id")),
            run_context=RunContext(
                data_mode=DataMode(str(_required(context, "data_mode"))),
                deployment_stage=DeploymentStage(str(_required(context, "deployment_stage"))),
            ),
            trust_state=DataTrustState(str(_required(document, "trust_state"))),
            latest_input_available_at=_datetime(
                _required(document, "latest_input_available_at"),
                "latest_input_available_at",
            ),
        )
        duplicates_match = (
            str(row[0]) == value.view_id
            and str(row[2]) == value.security_id
            and _datetime(row[3], "decision_time") == value.decision_time
            and _integer(row[4], "horizon_trading_days") == value.horizon_trading_days
            and str(row[5]) == value.run_context.data_mode.value
            and str(row[6]) == value.run_context.deployment_stage.value
            and str(row[7]) == value.trust_state.value
            and _datetime(row[8], "data_cutoff") == value.latest_input_available_at
            and str(row[9]) == value.model_version_id
            and str(row[10]) == value.run_id
        )
        if not duplicates_match:
            raise ValueError(f"stored InvestmentView columns mismatch: {value.view_id}")
        if value.content_hash != str(row[1]):
            raise ValueError(f"stored InvestmentView hash mismatch: {value.view_id}")
        return value

    @staticmethod
    def _component_from_document(document: Mapping[object, object]) -> InvestmentComponent:
        contribution = _required(document, "expected_return_contribution")
        reason = _required(document, "status_reason")
        return InvestmentComponent(
            name=str(_required(document, "name")),
            status=InvestmentComponentStatus(str(_required(document, "status"))),
            expected_return_contribution=(
                None
                if contribution is None
                else _decimal(contribution, "expected_return_contribution")
            ),
            evidence_ids=_strings(
                _required(document, "evidence_ids"),
                "component evidence_ids",
            ),
            status_reason=None if reason is None else str(reason),
        )

    @staticmethod
    def _outcome_from_row(row: Sequence[object]) -> InvestmentViewOutcome:
        document = _mapping(row[10], "outcome_document")
        value = InvestmentViewOutcome(
            outcome_id=str(_required(document, "outcome_id")),
            view_id=str(_required(document, "view_id")),
            security_id=str(_required(document, "security_id")),
            decision_time=_datetime(
                _required(document, "decision_time"),
                "decision_time",
            ),
            horizon_trading_days=_integer(
                _required(document, "horizon_trading_days"),
                "horizon_trading_days",
            ),
            realized_at=_datetime(
                _required(document, "realized_at"),
                "realized_at",
            ),
            realized_return=_decimal(
                _required(document, "realized_return"),
                "realized_return",
            ),
            dataset_version_id=str(_required(document, "dataset_version_id")),
            source_policy_version=str(
                _required(document, "source_policy_version")
            ),
            source_available_at=_datetime(
                _required(document, "source_available_at"),
                "source_available_at",
            ),
            recorded_at=_datetime(
                _required(document, "recorded_at"),
                "recorded_at",
            ),
        )
        duplicates_match = (
            str(row[0]) == value.outcome_id
            and str(row[2]) == value.view_id
            and str(row[3]) == value.security_id
            and _datetime(row[4], "decision_time") == value.decision_time
            and _integer(row[5], "horizon_trading_days") == value.horizon_trading_days
            and _datetime(row[6], "realized_at") == value.realized_at
            and str(row[7]) == value.dataset_version_id
            and str(row[8]) == value.source_policy_version
            and _datetime(row[9], "source_available_at") == value.source_available_at
            and _datetime(row[11], "recorded_at") == value.recorded_at
        )
        if not duplicates_match:
            raise ValueError(f"stored InvestmentView outcome columns mismatch: {value.outcome_id}")
        if value.content_hash != str(row[1]):
            raise ValueError(f"stored InvestmentView outcome hash mismatch: {value.outcome_id}")
        return value

    @staticmethod
    def _calibration_from_row(row: Sequence[object]) -> ExpectedReturnCalibrationRecord:
        document = _mapping(row[4], "calibration_document")
        value = ExpectedReturnCalibrationRecord(
            calibration_id=str(_required(document, "calibration_id")),
            view_id=str(_required(document, "view_id")),
            outcome_id=str(_required(document, "outcome_id")),
            predicted_return=_decimal(
                _required(document, "predicted_return"),
                "predicted_return",
            ),
            realized_return=_decimal(
                _required(document, "realized_return"),
                "realized_return",
            ),
            absolute_error=_decimal(
                _required(document, "absolute_error"),
                "absolute_error",
            ),
            inside_p10_p90=_boolean(
                _required(document, "inside_p10_p90"),
                "inside_p10_p90",
            ),
            direction_correct=_boolean(
                _required(document, "direction_correct"),
                "direction_correct",
            ),
            recorded_at=_datetime(
                _required(document, "recorded_at"),
                "recorded_at",
            ),
        )
        duplicates_match = (
            str(row[0]) == value.calibration_id
            and str(row[2]) == value.view_id
            and str(row[3]) == value.outcome_id
            and _datetime(row[5], "recorded_at") == value.recorded_at
        )
        if not duplicates_match:
            raise ValueError(
                f"stored Expected Return calibration columns mismatch: {value.calibration_id}"
            )
        if value.content_hash != str(row[1]):
            raise ValueError(
                f"stored Expected Return calibration hash mismatch: {value.calibration_id}"
            )
        return value


__all__ = ["PostgresExpectedReturnLedgerRepository"]
