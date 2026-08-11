"""PostgreSQL repositories with physical feature/label separation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, cast

from a_share_platform.domain.features import (
    FeatureCalculationStatus,
    FeaturePeriod,
    FeatureSnapshot,
    FeatureValueStage,
    LabelSchema,
    LabelValue,
)
from a_share_platform.domain.governance import VersionConflictError
from a_share_platform.domain.metrics import MetricUnit


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    return Jsonb(value)


def _json_array(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        value = json.loads(value)
    elif hasattr(value, "obj"):
        value = value.obj
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"stored {field_name} must be an array")
    return tuple(str(item) for item in value)


def _decimal(value: object, field_name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"stored {field_name} is not a decimal") from error
    if not result.is_finite():
        raise ValueError(f"stored {field_name} must be finite")
    return result


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...


class PostgresFeatureSnapshotRepository:
    """Production-safe append-only feature repository with no label methods."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save_snapshot(self, value: FeatureSnapshot) -> FeatureSnapshot:
        existing = self.get_snapshot(value.snapshot_id)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable feature snapshot identifier conflict: {value.snapshot_id}"
                )
            return existing
        row = self.to_row(value)
        params = tuple(
            _json_parameter(item) if index in {19, 20, 21} else item
            for index, item in enumerate(row)
        )
        self._connection.execute(
            """
            INSERT INTO research.feature_snapshots (
                snapshot_id, content_hash, feature_id, feature_version,
                feature_definition_hash, formula_version, missing_policy_version,
                winsorization_version, standardization_version, neutralization_version,
                entity_id, as_of, system_as_of, status, feature_value, value_stage,
                unit, currency, period, missing_input_names, dataset_version_ids,
                input_content_hashes
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (snapshot_id) DO NOTHING
            """,
            params,
        )
        stored = self.get_snapshot(value.snapshot_id)
        if stored is None:
            raise RuntimeError("feature snapshot insert was not observable")
        if stored != value:
            raise VersionConflictError(
                f"immutable feature snapshot identifier conflict: {value.snapshot_id}"
            )
        return stored

    def get_snapshot(self, snapshot_id: str) -> FeatureSnapshot | None:
        row = self._connection.execute(
            self._select() + " WHERE snapshot_id = %s",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _columns() -> str:
        return """
            snapshot_id, content_hash, feature_id, feature_version,
            feature_definition_hash, formula_version, missing_policy_version,
            winsorization_version, standardization_version, neutralization_version,
            entity_id, as_of, system_as_of, status, feature_value, value_stage,
            unit, currency, period, missing_input_names, dataset_version_ids,
            input_content_hashes
        """

    @classmethod
    def _select(cls) -> str:
        return "SELECT " + cls._columns() + " FROM research.feature_snapshots"

    @staticmethod
    def to_row(value: FeatureSnapshot) -> tuple[object, ...]:
        return (
            value.snapshot_id,
            value.content_hash,
            value.feature_id,
            value.feature_version,
            value.feature_definition_hash,
            value.formula_version,
            value.missing_policy_version,
            value.winsorization_version,
            value.standardization_version,
            value.neutralization_version,
            value.entity_id,
            value.as_of,
            value.system_as_of,
            value.status.value,
            None if value.value is None else str(value.value),
            value.value_stage.value,
            value.unit.value,
            value.currency,
            value.period.value,
            list(value.missing_input_names),
            list(value.dataset_version_ids),
            list(value.input_content_hashes),
        )

    @classmethod
    def _from_row(cls, row: Sequence[object]) -> FeatureSnapshot:
        value = FeatureSnapshot(
            snapshot_id=str(row[0]),
            feature_id=str(row[2]),
            feature_version=str(row[3]),
            feature_definition_hash=str(row[4]),
            formula_version=str(row[5]),
            missing_policy_version=str(row[6]),
            winsorization_version=str(row[7]),
            standardization_version=str(row[8]),
            neutralization_version=str(row[9]),
            entity_id=str(row[10]),
            as_of=cast(datetime, row[11]),
            system_as_of=cast(datetime, row[12]),
            status=FeatureCalculationStatus(str(row[13])),
            value=None if row[14] is None else _decimal(row[14], "feature_value"),
            value_stage=FeatureValueStage(str(row[15])),
            unit=MetricUnit(str(row[16])),
            currency=None if row[17] is None else str(row[17]),
            period=FeaturePeriod(str(row[18])),
            missing_input_names=_json_array(row[19], "missing_input_names"),
            dataset_version_ids=_json_array(row[20], "dataset_version_ids"),
            input_content_hashes=_json_array(row[21], "input_content_hashes"),
        )
        if value.content_hash != str(row[1]):
            raise VersionConflictError(
                f"immutable feature snapshot content conflict: {value.snapshot_id}"
            )
        return value


class PostgresResearchLabelRepository:
    """Research-only append-only label repository."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def save_label(self, value: LabelValue) -> LabelValue:
        existing = self.get_label(value.content_hash)
        if existing is not None:
            if existing != value:
                raise VersionConflictError(
                    f"immutable research label conflict: {value.content_hash}"
                )
            return existing
        self._connection.execute(
            """
            INSERT INTO research.research_labels (
                content_hash, label_id, label_version, schema_hash, horizon_sessions,
                unit, currency, period, label_value, entity_id, as_of,
                dataset_version_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_hash) DO NOTHING
            """,
            self.to_row(value),
        )
        stored = self.get_label(value.content_hash)
        if stored is None:
            raise RuntimeError("research label insert was not observable")
        if stored != value:
            raise VersionConflictError(
                f"immutable research label conflict: {value.content_hash}"
            )
        return stored

    def get_label(self, content_hash: str) -> LabelValue | None:
        row = self._connection.execute(
            self._select() + " WHERE content_hash = %s",
            (content_hash,),
        ).fetchone()
        return None if row is None else self._from_row(row)

    @staticmethod
    def _columns() -> str:
        return """
            content_hash, label_id, label_version, schema_hash, horizon_sessions,
            unit, currency, period, label_value, entity_id, as_of, dataset_version_id
        """

    @classmethod
    def _select(cls) -> str:
        return "SELECT " + cls._columns() + " FROM research.research_labels"

    @staticmethod
    def to_row(value: LabelValue) -> tuple[object, ...]:
        return (
            value.content_hash,
            value.schema.label_id,
            value.schema.version,
            value.schema.schema_hash,
            value.schema.horizon_sessions,
            value.schema.unit.value,
            value.schema.currency,
            value.schema.period.value,
            str(value.value),
            value.entity_id,
            value.as_of,
            value.dataset_version_id,
        )

    @classmethod
    def _from_row(cls, row: Sequence[object]) -> LabelValue:
        value = LabelValue(
            schema=LabelSchema(
                label_id=str(row[1]),
                version=str(row[2]),
                horizon_sessions=int(cast(int, row[4])),
                unit=MetricUnit(str(row[5])),
                currency=None if row[6] is None else str(row[6]),
                period=FeaturePeriod(str(row[7])),
            ),
            entity_id=str(row[9]),
            as_of=cast(datetime, row[10]),
            value=_decimal(row[8], "label_value"),
            dataset_version_id=str(row[11]),
        )
        if value.schema.schema_hash != str(row[3]):
            raise VersionConflictError(
                f"immutable research label schema conflict: {row[0]}"
            )
        if value.content_hash != str(row[0]):
            raise VersionConflictError(f"immutable research label conflict: {row[0]}")
        return value


__all__ = [
    "PostgresFeatureSnapshotRepository",
    "PostgresResearchLabelRepository",
]
