import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

from a_share_platform.domain.experiments import (
    ExperimentArtifact,
    ExperimentEnvironment,
    ExperimentFailure,
    ExperimentMetric,
    ExperimentParameter,
    ExperimentRun,
    ExperimentRunConflict,
    ExperimentRunRegistry,
    ExperimentRunStatus,
    ExperimentSpec,
    ExperimentTimeSplit,
    FeatureVersionBinding,
    LabelVersionBinding,
)
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext


def digest(character: str) -> str:
    return character * 64


def time_split() -> ExperimentTimeSplit:
    return ExperimentTimeSplit(
        train_start=date(2018, 1, 1),
        train_end_exclusive=date(2022, 1, 1),
        validation_start=date(2022, 1, 1),
        validation_end_exclusive=date(2024, 1, 1),
        test_start=date(2024, 1, 1),
        test_end_exclusive=date(2026, 1, 1),
        version="time-split:v1",
    )


def environment() -> ExperimentEnvironment:
    return ExperimentEnvironment(
        environment_id="environment:p4-research:v1",
        python_version="3.12.13",
        platform="macos-arm64",
        dependency_lock_hash=digest("e"),
    )


def feature(feature_id: str, marker: str) -> FeatureVersionBinding:
    return FeatureVersionBinding(
        feature_id=feature_id,
        version="v1",
        definition_hash=digest(marker),
    )


def label(label_id: str = "label:forward-return-20d") -> LabelVersionBinding:
    return LabelVersionBinding(
        label_id=label_id,
        version="v1",
        schema_hash=digest("c"),
        dataset_version_id="dataset:labels:v1",
    )


def spec(**overrides: object) -> ExperimentSpec:
    values: dict[str, object] = {
        "spec_id": "experiment-spec:quality-csi300:v1",
        "research_question": "Does the quality factor predict forward returns?",
        "run_context": RunContext(
            data_mode=DataMode.STRICT_HISTORICAL,
            deployment_stage=DeploymentStage.RESEARCH,
        ),
        "decision_time_policy_version": "decision-time:close-plus-one:v1",
        "readiness_evidence_hash": digest("f"),
        "universe_version_id": "universe:csi300:pit:v1",
        "dataset_version_ids": (
            "dataset:labels:v1",
            "dataset:pit-financials:v1",
            "dataset:raw-bars:v1",
        ),
        "feature_bindings": (
            feature("feature:cash-conversion", "a"),
            feature("feature:roic", "b"),
        ),
        "label_bindings": (label(),),
        "time_split": time_split(),
        "code_sha": "1" * 40,
        "parameters": (
            ExperimentParameter("minimum_coverage", "0.80"),
            ExperimentParameter("winsorization", "winsor:v1"),
        ),
        "random_seed": 20260811,
        "environment": environment(),
        "metric_names": ("rank_ic", "turnover"),
    }
    values.update(overrides)
    return ExperimentSpec(**values)  # type: ignore[arg-type]


def artifact(marker: str = "d") -> ExperimentArtifact:
    return ExperimentArtifact(
        artifact_id=f"artifact:experiment:{marker}",
        kind="validation-report",
        media_type="application/json",
        content_hash=digest(marker),
    )


def metric(name: str, value: str) -> ExperimentMetric:
    return ExperimentMetric(
        name=name,
        version="metric:v1",
        value=Decimal(value),
        unit="ratio",
    )


class ExperimentSpecTest(unittest.TestCase):
    def test_spec_freezes_and_canonicalizes_every_reproducibility_binding(self) -> None:
        left = spec()
        right = spec(
            dataset_version_ids=tuple(reversed(left.dataset_version_ids)),
            feature_bindings=tuple(reversed(left.feature_bindings)),
            metric_names=tuple(reversed(left.metric_names)),
        )

        self.assertEqual(left.content_hash, right.content_hash)
        self.assertEqual(left.dataset_version_ids, tuple(sorted(left.dataset_version_ids)))
        self.assertEqual(
            tuple(item.feature_id for item in left.feature_bindings),
            ("feature:cash-conversion", "feature:roic"),
        )
        self.assertEqual(left.random_seed, 20260811)
        self.assertEqual(left.code_sha, "1" * 40)
        self.assertTrue(left.historical_evidence_eligible)
        with self.assertRaises(FrozenInstanceError):
            left.random_seed = 0  # type: ignore[misc]

    def test_missing_reproducibility_bindings_fail_closed(self) -> None:
        base = spec()
        invalid_values = (
            ("research_question", ""),
            ("decision_time_policy_version", ""),
            ("readiness_evidence_hash", "not-a-hash"),
            ("universe_version_id", ""),
            ("dataset_version_ids", ()),
            ("feature_bindings", ()),
            ("label_bindings", ()),
            ("code_sha", "not-a-sha"),
            ("metric_names", ()),
            ("random_seed", -1),
        )
        for field_name, value in invalid_values:
            with self.subTest(field=field_name), self.assertRaises((TypeError, ValueError)):
                replace(base, **{field_name: value})

        current = replace(
            base,
            run_context=RunContext(
                data_mode=DataMode.CURRENT_RESEARCH,
                deployment_stage=DeploymentStage.RESEARCH,
            ),
        )
        self.assertFalse(current.historical_evidence_eligible)
        self.assertNotEqual(base.content_hash, current.content_hash)

    def test_label_binding_cannot_enter_the_feature_binding_collection(self) -> None:
        with self.assertRaisesRegex(TypeError, "FeatureVersionBinding"):
            spec(feature_bindings=(label(),))

    def test_label_dataset_must_be_frozen_in_the_data_binding(self) -> None:
        with self.assertRaisesRegex(ValueError, "label dataset_version_id"):
            spec(dataset_version_ids=("dataset:pit-financials:v1",))

    def test_time_split_is_half_open_ordered_and_non_overlapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "train interval"):
            replace(
                time_split(),
                train_end_exclusive=date(2018, 1, 1),
            )
        with self.assertRaisesRegex(ValueError, "overlap"):
            replace(
                time_split(),
                validation_start=date(2021, 12, 31),
            )


class ExperimentRunTest(unittest.TestCase):
    def test_successful_run_binds_declared_metrics_artifacts_and_spec_hash(self) -> None:
        value = ExperimentRun(
            run_id="experiment-run:quality-csi300:001",
            spec=spec(),
            status=ExperimentRunStatus.SUCCEEDED,
            started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
            metrics=(metric("turnover", "0.12"), metric("rank_ic", "0.031")),
            artifacts=(artifact(),),
            failure=None,
        )

        self.assertEqual(value.spec_hash, value.spec.content_hash)
        self.assertEqual(
            tuple(item.name for item in value.metrics),
            ("rank_ic", "turnover"),
        )
        self.assertEqual(value.artifacts[0].content_hash, digest("d"))
        with self.assertRaises(FrozenInstanceError):
            value.status = ExperimentRunStatus.FAILED  # type: ignore[misc]

    def test_failed_run_is_registered_and_retains_failure_evidence(self) -> None:
        failure = ExperimentFailure(
            stage="metric-evaluation",
            error_type="CoverageGateError",
            message="coverage 0.62 is below 0.80",
            occurred_at=datetime(2026, 8, 11, 1, 30, tzinfo=UTC),
            retryable=False,
        )
        failed = ExperimentRun(
            run_id="experiment-run:quality-csi300:failed-001",
            spec=spec(),
            status=ExperimentRunStatus.FAILED,
            started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
            metrics=(metric("rank_ic", "0.005"),),
            artifacts=(artifact("f"),),
            failure=failure,
        )

        registry = ExperimentRunRegistry().register(failed)

        self.assertEqual(registry.runs, (failed,))
        self.assertEqual(registry.failed_runs, (failed,))
        self.assertEqual(registry.runs[0].failure, failure)
        self.assertNotEqual(registry.runs[0].metrics[0].value, Decimal(0))

    def test_terminal_status_invariants_fail_closed(self) -> None:
        base = ExperimentRun(
            run_id="experiment-run:quality-csi300:001",
            spec=spec(),
            status=ExperimentRunStatus.SUCCEEDED,
            started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
            metrics=(metric("rank_ic", "0.031"), metric("turnover", "0.12")),
            artifacts=(artifact(),),
            failure=None,
        )
        invalid = (
            {"metrics": ()},
            {"artifacts": ()},
            {"finished_at": None},
            {
                "status": ExperimentRunStatus.FAILED,
                "failure": None,
            },
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(base, **changes)

        with self.assertRaisesRegex(TypeError, "immutable failure evidence"):
            replace(
                base,
                status=ExperimentRunStatus.FAILED,
                failure=cast(ExperimentFailure, object()),
            )

    def test_success_requires_exact_declared_metric_family(self) -> None:
        with self.assertRaisesRegex(ValueError, "declared metric family"):
            ExperimentRun(
                run_id="experiment-run:quality-csi300:001",
                spec=spec(),
                status=ExperimentRunStatus.SUCCEEDED,
                started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
                finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
                metrics=(metric("rank_ic", "0.031"),),
                artifacts=(artifact(),),
                failure=None,
            )

    def test_registry_is_append_only_idempotent_and_rejects_run_id_conflict(self) -> None:
        run = ExperimentRun(
            run_id="experiment-run:quality-csi300:001",
            spec=spec(),
            status=ExperimentRunStatus.SUCCEEDED,
            started_at=datetime(2026, 8, 11, 1, tzinfo=UTC),
            finished_at=datetime(2026, 8, 11, 2, tzinfo=UTC),
            metrics=(metric("rank_ic", "0.031"), metric("turnover", "0.12")),
            artifacts=(artifact(),),
            failure=None,
        )
        registry = ExperimentRunRegistry().register(run)

        self.assertIs(registry.register(run), registry)
        conflicting = replace(run, artifacts=(artifact("a"),))
        with self.assertRaises(ExperimentRunConflict):
            registry.register(conflicting)


if __name__ == "__main__":
    unittest.main()
