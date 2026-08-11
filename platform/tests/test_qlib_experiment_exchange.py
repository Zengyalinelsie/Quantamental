import json
import unittest
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from types import MappingProxyType

from a_share_platform.adapters.memory.experiments import InMemoryExperimentRunRepository
from a_share_platform.adapters.qlib.recorder import (
    QlibExperimentAdapter,
    QlibRecorderRecord,
)
from a_share_platform.application.experiment_exchange import ExperimentExchangeService
from a_share_platform.domain.experiments import (
    ExperimentArtifact,
    ExperimentEnvironment,
    ExperimentMetric,
    ExperimentParameter,
    ExperimentRun,
    ExperimentRunStatus,
    ExperimentSpec,
    ExperimentTimeSplit,
    FeatureVersionBinding,
    LabelVersionBinding,
)
from a_share_platform.domain.factor_lifecycle import (
    FactorVersion,
    ValidationCheck,
    ValidationCheckName,
    ValidationOutcome,
    ValidationReport,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.experiment_exchange import (
    ExperimentEngineUnavailable,
    RecorderArtifactField,
    RecorderImportError,
    RecorderImportRequest,
    RecorderImportSchema,
    RecorderMetricField,
)

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)


def digest(marker: str) -> str:
    return marker * 64


def spec() -> ExperimentSpec:
    return ExperimentSpec(
        spec_id="experiment-spec:quality-csi300:v1",
        research_question="Does quality predict forward returns?",
        run_context=RunContext(
            DataMode.STRICT_HISTORICAL,
            DeploymentStage.RESEARCH,
        ),
        decision_time_policy_version="decision-time:close-plus-one:v1",
        readiness_evidence_hash=digest("f"),
        universe_version_id="universe:csi300:pit:v1",
        dataset_version_ids=(
            "dataset:labels:v1",
            "dataset:pit-financials:v1",
            "dataset:raw-bars:v1",
        ),
        feature_bindings=(
            FeatureVersionBinding("feature:cash-conversion", "v1", digest("a")),
            FeatureVersionBinding("feature:roic", "v1", digest("b")),
        ),
        label_bindings=(
            LabelVersionBinding(
                "label:forward-return-20d",
                "v1",
                digest("c"),
                "dataset:labels:v1",
            ),
        ),
        time_split=ExperimentTimeSplit(
            train_start=date(2018, 1, 1),
            train_end_exclusive=date(2022, 1, 1),
            validation_start=date(2022, 1, 1),
            validation_end_exclusive=date(2024, 1, 1),
            test_start=date(2024, 1, 1),
            test_end_exclusive=date(2026, 1, 1),
            version="time-split:v1",
        ),
        code_sha="1" * 40,
        parameters=(ExperimentParameter("winsorization", "winsor:v1"),),
        random_seed=20260811,
        environment=ExperimentEnvironment(
            environment_id="environment:p4-research:v1",
            python_version="3.12.13",
            platform="macos-arm64",
            dependency_lock_hash=digest("e"),
        ),
        metric_names=("rank_ic", "turnover"),
    )


def artifact(marker: str = "d") -> ExperimentArtifact:
    return ExperimentArtifact(
        artifact_id=f"artifact:validation:{marker}",
        kind="validation-report",
        media_type="application/json",
        content_hash=digest(marker),
    )


def metric(name: str, value: str) -> ExperimentMetric:
    return ExperimentMetric(name, "metric:v1", Decimal(value), "ratio")


def succeeded_run() -> ExperimentRun:
    return ExperimentRun(
        run_id="experiment-run:quality:001",
        spec=spec(),
        status=ExperimentRunStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW.replace(hour=9),
        metrics=(metric("rank_ic", "0.031"), metric("turnover", "0.12")),
        artifacts=(artifact(),),
        failure=None,
    )


def factor() -> FactorVersion:
    return FactorVersion(
        factor_version_id="factor-version:quality:v1",
        factor_id="factor:quality",
        semantic_version="1.0.0",
        definition_hash=digest("4"),
        code_sha="1" * 40,
        dataset_version_ids=("dataset:pit-financials:v1",),
        feature_version_ids=(
            "feature:cash-conversion:v1",
            "feature:roic:v1",
        ),
        model_version_ids=(),
        created_by="user:researcher-01",
        created_at=NOW.replace(day=10),
    )


def checks(
    *, failed: ValidationCheckName | None = None
) -> tuple[ValidationCheck, ...]:
    return tuple(
        ValidationCheck(
            name=name,
            outcome=(
                ValidationOutcome.FAIL
                if name is failed
                else ValidationOutcome.PASS
            ),
            evidence_hashes=(digest("9" if name is failed else "8"),),
            detail="Frozen validation evidence.",
        )
        for name in ValidationCheckName
    )


def report(
    *, failed: ValidationCheckName | None = None,
) -> ValidationReport:
    return ValidationReport(
        report_id="validation-report:quality:v1",
        report_version="v1",
        factor_version_id="factor-version:quality:v1",
        experiment_run_id="experiment-run:quality:001",
        dataset_version_ids=spec().dataset_version_ids,
        code_sha="1" * 40,
        artifact_hashes=(digest("d"),),
        run_context=spec().run_context,
        input_trust_state=DataTrustState.PIT_VERIFIED,
        checks=checks(failed=failed),
        created_at=NOW.replace(hour=10),
    )


@dataclass
class FixtureRecord:
    recorder_id: str
    status: str
    started_at: object
    finished_at: object
    metrics: Mapping[str, object]
    objects: Mapping[str, object]

    def load_object(self, name: str) -> object:
        if name not in self.objects:
            raise KeyError(name)
        return self.objects[name]


class FixtureGateway:
    def __init__(self, record: FixtureRecord | None = None) -> None:
        self.record = record
        self.exports: list[tuple[str, str, Mapping[str, str], Mapping[str, bytes]]] = []

    def create_recorder(
        self,
        *,
        experiment_name: str,
        recorder_name: str,
        parameters: Mapping[str, str],
        objects: Mapping[str, bytes],
    ) -> str:
        self.exports.append((experiment_name, recorder_name, parameters, objects))
        return "qlib-recorder:export:001"

    def get_recorder(
        self,
        *,
        experiment_name: str,
        recorder_id: str,
    ) -> QlibRecorderRecord:
        if self.record is None or self.record.recorder_id != recorder_id:
            raise KeyError(recorder_id)
        return self.record


def import_schema() -> RecorderImportSchema:
    return RecorderImportSchema(
        schema_version="a-share-platform.recorder-import.v1",
        succeeded_status="FINISHED",
        failed_status="FAILED",
        metric_fields=(
            RecorderMetricField("rank_ic", "rank_ic", "metric:v1", "ratio"),
            RecorderMetricField("turnover", "turnover", "metric:v1", "ratio"),
        ),
        artifact_fields=(
            RecorderArtifactField(
                "validation.json",
                "artifact:qlib:validation:001",
                "validation-report",
                "application/json",
            ),
        ),
        failure_object_name="failure.json",
    )


def import_request() -> RecorderImportRequest:
    return RecorderImportRequest(
        run_id="experiment-run:quality:qlib-001",
        spec=spec(),
        experiment_name="quality-csi300-v1",
        recorder_id="qlib-recorder:001",
        schema=import_schema(),
    )


class ExperimentExportTest(unittest.TestCase):
    def test_export_freezes_complete_reproducibility_and_validation_lineage(self) -> None:
        gateway = FixtureGateway()
        adapter = QlibExperimentAdapter(gateway)
        service = ExperimentExchangeService(
            exporter=adapter,
            recorder_importer=adapter,
            repository=InMemoryExperimentRunRepository(),
        )

        receipt = service.export(
            run=succeeded_run(),
            factor_version=factor(),
            validation_report=report(),
            experiment_name="quality-csi300-v1",
            recorder_name="frozen-export-001",
        )

        self.assertEqual(receipt.engine_id, "qlib")
        self.assertEqual(receipt.recorder_id, "qlib-recorder:export:001")
        self.assertEqual(len(gateway.exports), 1)
        _, _, parameters, objects = gateway.exports[0]
        manifest = json.loads(objects["a_share_frozen_lineage.json"])
        self.assertEqual(parameters["a_share_export_hash"], receipt.export_content_hash)
        self.assertEqual(
            manifest["dataset_version_ids"],
            list(succeeded_run().spec.dataset_version_ids),
        )
        self.assertEqual(manifest["universe_version_id"], "universe:csi300:pit:v1")
        self.assertEqual(
            {item["feature_id"] for item in manifest["feature_bindings"]},
            {"feature:cash-conversion", "feature:roic"},
        )
        self.assertEqual(manifest["code"]["experiment_spec_sha"], "1" * 40)
        self.assertEqual(
            manifest["environment"]["dependency_lock_hash"],
            digest("e"),
        )
        self.assertEqual(
            manifest["validation"]["report_hash"],
            report().content_hash,
        )
        self.assertEqual(
            len(manifest["validation"]["checks"]),
            len(ValidationCheckName),
        )

    def test_binding_mismatch_fails_before_qlib_is_called(self) -> None:
        gateway = FixtureGateway()
        adapter = QlibExperimentAdapter(gateway)
        service = ExperimentExchangeService(
            exporter=adapter,
            recorder_importer=adapter,
            repository=InMemoryExperimentRunRepository(),
        )
        invalid_factor = replace(
            factor(),
            dataset_version_ids=("dataset:not-in-experiment:v1",),
        )

        with self.assertRaisesRegex(ValueError, "dataset lineage"):
            service.export(
                run=succeeded_run(),
                factor_version=invalid_factor,
                validation_report=report(),
                experiment_name="quality-csi300-v1",
                recorder_name="invalid",
            )

        self.assertEqual(gateway.exports, [])

    def test_failed_validation_is_exported_honestly_and_never_promoted(self) -> None:
        gateway = FixtureGateway()
        adapter = QlibExperimentAdapter(gateway)
        service = ExperimentExchangeService(
            exporter=adapter,
            recorder_importer=adapter,
            repository=InMemoryExperimentRunRepository(),
        )

        service.export(
            run=succeeded_run(),
            factor_version=factor(),
            validation_report=report(failed=ValidationCheckName.FDR),
            experiment_name="quality-csi300-v1",
            recorder_name="failed-validation",
        )

        manifest = json.loads(gateway.exports[0][3]["a_share_frozen_lineage.json"])
        self.assertFalse(manifest["validation"]["passes_promotion_gate"])
        fdr = next(
            item for item in manifest["validation"]["checks"] if item["name"] == "fdr"
        )
        self.assertEqual(fdr["outcome"], "fail")


class RecorderImportTest(unittest.TestCase):
    def _service(self, record: FixtureRecord) -> ExperimentExchangeService:
        adapter = QlibExperimentAdapter(FixtureGateway(record))
        return ExperimentExchangeService(
            exporter=adapter,
            recorder_importer=adapter,
            repository=InMemoryExperimentRunRepository(),
        )

    def test_explicit_schema_imports_exact_metrics_and_content_hashed_artifacts(self) -> None:
        payload = b'{"validation":"frozen"}'
        record = FixtureRecord(
            recorder_id="qlib-recorder:001",
            status="FINISHED",
            started_at=NOW,
            finished_at=NOW.replace(hour=9),
            metrics=MappingProxyType({"rank_ic": "0.031", "turnover": 0.12}),
            objects=MappingProxyType({"validation.json": payload}),
        )

        imported = self._service(record).import_and_register(import_request())

        self.assertEqual(imported.status, ExperimentRunStatus.SUCCEEDED)
        self.assertEqual(tuple(item.name for item in imported.metrics), ("rank_ic", "turnover"))
        self.assertEqual(imported.metrics[0].value, Decimal("0.031"))
        self.assertEqual(
            imported.artifacts[0].content_hash,
            "55e46f481b34ac44dac8aad19cada0b506a25b7787fe917b2aa8bc28c10dc1f2",
        )

    def test_missing_or_undeclared_metric_fails_closed(self) -> None:
        for metrics in (
            {"rank_ic": "0.031"},
            {"rank_ic": "0.031", "turnover": "0.12", "sharpe": "9.9"},
        ):
            with self.subTest(metrics=metrics):
                record = FixtureRecord(
                    recorder_id="qlib-recorder:001",
                    status="FINISHED",
                    started_at=NOW,
                    finished_at=NOW.replace(hour=9),
                    metrics=metrics,
                    objects={"validation.json": b"{}"},
                )
                with self.assertRaisesRegex(RecorderImportError, "metric schema"):
                    self._service(record).import_and_register(import_request())

    def test_unsupported_or_incomplete_explicit_schema_fails_closed(self) -> None:
        record = FixtureRecord(
            recorder_id="qlib-recorder:001",
            status="FINISHED",
            started_at=NOW,
            finished_at=NOW.replace(hour=9),
            metrics={"rank_ic": "0.031", "turnover": "0.12"},
            objects={"validation.json": b"{}"},
        )
        requests = (
            replace(
                import_request(),
                schema=replace(import_schema(), schema_version="unknown:v9"),
            ),
            replace(
                import_request(),
                schema=replace(
                    import_schema(),
                    metric_fields=import_schema().metric_fields[:-1],
                ),
            ),
        )
        for request in requests:
            with self.subTest(schema=request.schema), self.assertRaises(
                RecorderImportError
            ):
                self._service(record).import_and_register(request)

    def test_missing_artifact_and_non_finite_metric_fail_closed(self) -> None:
        records = (
            FixtureRecord(
                "qlib-recorder:001",
                "FINISHED",
                NOW,
                NOW.replace(hour=9),
                {"rank_ic": "0.031", "turnover": "0.12"},
                {},
            ),
            FixtureRecord(
                "qlib-recorder:001",
                "FINISHED",
                NOW,
                NOW.replace(hour=9),
                {"rank_ic": "NaN", "turnover": "0.12"},
                {"validation.json": b"{}"},
            ),
        )
        for record in records:
            with self.subTest(record=record), self.assertRaises(RecorderImportError):
                self._service(record).import_and_register(import_request())

    def test_failed_recorder_requires_explicit_failure_schema_and_is_retained(self) -> None:
        failure = json.dumps(
            {
                "stage": "fit",
                "error_type": "CoverageGateError",
                "message": "coverage below threshold",
                "occurred_at": NOW.replace(minute=30).isoformat(),
                "retryable": False,
            },
            separators=(",", ":"),
        ).encode()
        record = FixtureRecord(
            recorder_id="qlib-recorder:001",
            status="FAILED",
            started_at=NOW,
            finished_at=NOW.replace(hour=9),
            metrics={"rank_ic": "0.001"},
            objects={"failure.json": failure},
        )

        imported = self._service(record).import_and_register(import_request())

        self.assertEqual(imported.status, ExperimentRunStatus.FAILED)
        self.assertEqual(imported.metrics[0].name, "rank_ic")
        self.assertEqual(imported.failure.error_type, "CoverageGateError")  # type: ignore[union-attr]

    def test_missing_failure_field_and_unknown_status_fail_closed(self) -> None:
        invalid_failure = b'{"stage":"fit"}'
        records = (
            FixtureRecord(
                "qlib-recorder:001",
                "FAILED",
                NOW,
                NOW.replace(hour=9),
                {},
                {"failure.json": invalid_failure},
            ),
            FixtureRecord(
                "qlib-recorder:001",
                "RUNNING",
                NOW,
                None,
                {},
                {},
            ),
        )
        for record in records:
            with self.subTest(status=record.status), self.assertRaises(RecorderImportError):
                self._service(record).import_and_register(import_request())

    def test_absent_qlib_sdk_is_explicitly_unavailable(self) -> None:
        def missing_runtime(_: str) -> object:
            raise ModuleNotFoundError("No module named 'qlib'")

        with self.assertRaisesRegex(ExperimentEngineUnavailable, "Qlib SDK is unavailable"):
            QlibExperimentAdapter.from_runtime(module_loader=missing_runtime)


if __name__ == "__main__":
    unittest.main()
