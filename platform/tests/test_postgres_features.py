import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from a_share_platform.adapters.postgres.features import (
    PostgresFeatureSnapshotRepository,
    PostgresResearchLabelRepository,
)
from a_share_platform.api.app import create_app
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

AS_OF = datetime(2026, 6, 30, 7, tzinfo=UTC)
SYSTEM_AS_OF = datetime(2026, 8, 10, 8, tzinfo=UTC)
FEATURE_VALUE = Decimal("17085765657.950001")
LABEL_VALUE = Decimal("0.1234567890123456789")


def json_payload(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    if hasattr(value, "obj"):
        return value.obj
    return value


def snapshot() -> FeatureSnapshot:
    return FeatureSnapshot(
        snapshot_id="feature-snapshot:600519:2026-06-30:quality:v1",
        feature_id="feature:quality:cash-conversion",
        feature_version="v1",
        feature_definition_hash="sha256:" + "a" * 64,
        formula_version="formula:v1",
        missing_policy_version="missing:v1",
        winsorization_version="winsor:v1",
        standardization_version="standardize:v1",
        neutralization_version="neutralize:v1",
        entity_id="security:CN:600519:XSHG",
        as_of=AS_OF,
        system_as_of=SYSTEM_AS_OF,
        status=FeatureCalculationStatus.QUANTIFIED,
        value=FEATURE_VALUE,
        value_stage=FeatureValueStage.NEUTRALIZED,
        unit=MetricUnit.CURRENCY,
        currency="CNY",
        period=FeaturePeriod.TTM,
        missing_input_names=(),
        dataset_version_ids=("dataset:financial:v2", "dataset:universe:v1"),
        input_content_hashes=(
            "sha256:" + "b" * 64,
            "sha256:" + "c" * 64,
        ),
    )


def label() -> LabelValue:
    return LabelValue(
        schema=LabelSchema(
            label_id="label:forward-return-20d",
            version="v1",
            horizon_sessions=20,
            unit=MetricUnit.RATIO,
            currency=None,
        ),
        entity_id="security:CN:600519:XSHG",
        as_of=AS_OF,
        value=LABEL_VALUE,
        dataset_version_id="dataset:forward-return-label:v1",
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]] | None = None) -> None:
        self.rows = rows or []

    def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeConnection:
    def __init__(
        self,
        *,
        feature_row: tuple[object, ...] | None = None,
        label_row: tuple[object, ...] | None = None,
    ) -> None:
        self.feature_row = feature_row
        self.label_row = label_row
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def execute(self, query: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append((query, params))
        normalized = " ".join(query.split())
        if normalized.startswith("INSERT INTO research.feature_snapshots"):
            self.feature_row = params
            return FakeResult()
        if normalized.startswith("INSERT INTO research.research_labels"):
            self.label_row = params
            return FakeResult()
        if "FROM research.feature_snapshots" in normalized:
            return FakeResult([] if self.feature_row is None else [self.feature_row])
        if "FROM research.research_labels" in normalized:
            return FakeResult([] if self.label_row is None else [self.label_row])
        return FakeResult()


class PostgresFeatureSnapshotRepositoryTest(unittest.TestCase):
    def test_append_only_insert_preserves_decimal_versions_and_input_hashes(self) -> None:
        value = snapshot()
        connection = FakeConnection()
        repository = PostgresFeatureSnapshotRepository(connection)

        self.assertEqual(repository.save_snapshot(value), value)

        query, params = next(
            call for call in connection.calls if "INSERT INTO research.feature_snapshots" in call[0]
        )
        self.assertIn("ON CONFLICT (snapshot_id) DO NOTHING", query)
        self.assertNotIn("UPDATE", query)
        self.assertEqual(params[14], str(FEATURE_VALUE))
        self.assertEqual(json_payload(params[20]), list(value.dataset_version_ids))
        self.assertEqual(json_payload(params[21]), list(value.input_content_hashes))
        self.assertEqual(repository.get_snapshot(value.snapshot_id), value)

    def test_reusing_snapshot_id_with_different_content_fails_closed(self) -> None:
        original = snapshot()
        connection = FakeConnection(
            feature_row=PostgresFeatureSnapshotRepository.to_row(original)
        )
        repository = PostgresFeatureSnapshotRepository(connection)

        with self.assertRaisesRegex(VersionConflictError, "immutable feature snapshot"):
            repository.save_snapshot(replace(original, value=Decimal(2)))

        self.assertFalse(any("UPDATE" in query for query, _params in connection.calls))


class PostgresResearchLabelRepositoryTest(unittest.TestCase):
    def test_label_uses_a_separate_table_repository_and_exact_decimal_round_trip(self) -> None:
        value = label()
        connection = FakeConnection()
        repository = PostgresResearchLabelRepository(connection)

        self.assertEqual(repository.save_label(value), value)

        query, params = next(
            call for call in connection.calls if "INSERT INTO research.research_labels" in call[0]
        )
        self.assertNotIn("feature_snapshots", query)
        self.assertIn("ON CONFLICT (content_hash) DO NOTHING", query)
        self.assertNotIn("UPDATE", query)
        self.assertEqual(params[8], str(LABEL_VALUE))
        self.assertEqual(repository.get_label(value.content_hash), value)

        feature_reader = PostgresFeatureSnapshotRepository(FakeConnection())
        self.assertFalse(hasattr(feature_reader, "get_label"))
        self.assertFalse(hasattr(feature_reader, "save_label"))

    def test_reusing_label_hash_with_different_stored_content_fails_closed(self) -> None:
        value = label()
        stored = list(PostgresResearchLabelRepository.to_row(value))
        stored[8] = "0.9"
        repository = PostgresResearchLabelRepository(
            FakeConnection(label_row=tuple(stored))
        )

        with self.assertRaisesRegex(VersionConflictError, "immutable research label"):
            repository.save_label(value)

    def test_default_api_does_not_expose_research_label_routes(self) -> None:
        paths = create_app().openapi()["paths"]
        self.assertFalse(any("label" in path for path in paths))


if __name__ == "__main__":
    unittest.main()
