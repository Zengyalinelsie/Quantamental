"""Freeze platform lineage before exchanging experiments with an outer engine."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from a_share_platform.domain.experiments import ExperimentRun
from a_share_platform.domain.factor_lifecycle import FactorVersion, ValidationReport
from a_share_platform.ports.experiment_exchange import (
    ExperimentExportAdapter,
    ExperimentExportReceipt,
    ExperimentRecorderImportAdapter,
    FrozenExperimentExport,
    RecorderImportError,
    RecorderImportRequest,
)
from a_share_platform.ports.experiments import ExperimentRunRepository

_EXPORT_SCHEMA = "a-share-platform.frozen-experiment-lineage.v1"


def _feature_version_id(feature_id: str, version: str) -> str:
    return f"{feature_id}:{version}"


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def freeze_experiment_export(
    *,
    run: ExperimentRun,
    factor_version: FactorVersion,
    validation_report: ValidationReport,
) -> FrozenExperimentExport:
    """Build one canonical, provider-neutral reproducibility manifest.

    The manifest records evidence, including failed validation.  Building or
    exporting it never promotes a factor and grants no execution authority.
    """

    if not isinstance(run, ExperimentRun):
        raise TypeError("run must be an ExperimentRun")
    if not isinstance(factor_version, FactorVersion):
        raise TypeError("factor_version must be a FactorVersion")
    if not isinstance(validation_report, ValidationReport):
        raise TypeError("validation_report must be a ValidationReport")
    spec = run.spec
    missing_factor_datasets = set(factor_version.dataset_version_ids).difference(
        spec.dataset_version_ids
    )
    if missing_factor_datasets:
        raise ValueError(
            "factor dataset lineage is outside the experiment spec: "
            + ", ".join(sorted(missing_factor_datasets))
        )
    spec_features = {
        _feature_version_id(value.feature_id, value.version)
        for value in spec.feature_bindings
    }
    missing_factor_features = set(factor_version.feature_version_ids).difference(
        spec_features
    )
    if missing_factor_features:
        raise ValueError(
            "factor feature lineage is outside the experiment spec: "
            + ", ".join(sorted(missing_factor_features))
        )
    if factor_version.code_sha != spec.code_sha:
        raise ValueError("factor code lineage does not match the experiment spec")
    if validation_report.factor_version_id != factor_version.factor_version_id:
        raise ValueError("validation lineage targets another FactorVersion")
    if validation_report.experiment_run_id != run.run_id:
        raise ValueError("validation lineage targets another ExperimentRun")
    if validation_report.dataset_version_ids != spec.dataset_version_ids:
        raise ValueError("validation dataset lineage does not match the experiment spec")
    if validation_report.code_sha != spec.code_sha:
        raise ValueError("validation code lineage does not match the experiment spec")
    if validation_report.run_context != spec.run_context:
        raise ValueError("validation RunContext does not match the experiment spec")
    run_artifact_hashes = {value.content_hash for value in run.artifacts}
    missing_validation_artifacts = set(validation_report.artifact_hashes).difference(
        run_artifact_hashes
    )
    if missing_validation_artifacts:
        raise ValueError(
            "validation artifact lineage is outside the experiment run: "
            + ", ".join(sorted(missing_validation_artifacts))
        )
    if run.finished_at is None:
        raise ValueError("validation lineage export requires a terminal experiment run")
    if validation_report.created_at < run.finished_at:
        raise ValueError("ValidationReport cannot precede its experiment run")

    document = {
        "schema_version": _EXPORT_SCHEMA,
        "experiment_run": {
            "run_id": run.run_id,
            "content_hash": run.content_hash,
            "status": run.status.value,
            "spec_id": spec.spec_id,
            "spec_hash": spec.content_hash,
            "started_at": (
                None if run.started_at is None else _canonical_time(run.started_at)
            ),
            "finished_at": _canonical_time(run.finished_at),
            "metrics": [
                {
                    "name": value.name,
                    "version": value.version,
                    "value": str(value.value),
                    "unit": value.unit,
                }
                for value in run.metrics
            ],
            "artifacts": [
                {
                    "artifact_id": value.artifact_id,
                    "kind": value.kind,
                    "media_type": value.media_type,
                    "content_hash": value.content_hash,
                }
                for value in run.artifacts
            ],
            "failure": (
                None
                if run.failure is None
                else {
                    "stage": run.failure.stage,
                    "error_type": run.failure.error_type,
                    "message": run.failure.message,
                    "occurred_at": _canonical_time(run.failure.occurred_at),
                    "retryable": run.failure.retryable,
                }
            ),
        },
        "factor_version": {
            "factor_version_id": factor_version.factor_version_id,
            "factor_id": factor_version.factor_id,
            "semantic_version": factor_version.semantic_version,
            "content_hash": factor_version.content_hash,
            "definition_hash": factor_version.definition_hash,
            "dataset_version_ids": factor_version.dataset_version_ids,
            "feature_version_ids": factor_version.feature_version_ids,
            "model_version_ids": factor_version.model_version_ids,
            "lifecycle_status": factor_version.status.value,
            "lifecycle_events": [
                {
                    "event_id": value.event_id,
                    "from_status": value.from_status.value,
                    "to_status": value.to_status.value,
                    "actor_id": value.actor_id,
                    "actor_role": value.actor_role,
                    "occurred_at": _canonical_time(value.occurred_at),
                    "reason": value.reason,
                    "evidence_hashes": value.evidence_hashes,
                }
                for value in factor_version.lifecycle_events
            ],
            "promotion_bindings": [
                {
                    "validation_report_id": value.validation_report_id,
                    "validation_report_hash": value.validation_report_hash,
                    "approval_id": value.approval_id,
                    "approval_hash": value.approval_hash,
                    "scope": value.scope.value,
                    "bound_at": _canonical_time(value.bound_at),
                }
                for value in factor_version.promotion_bindings
            ],
        },
        "run_context": {
            "data_mode": spec.run_context.data_mode.value,
            "deployment_stage": spec.run_context.deployment_stage.value,
        },
        "dataset_version_ids": spec.dataset_version_ids,
        "universe_version_id": spec.universe_version_id,
        "feature_bindings": [
            {
                "feature_id": value.feature_id,
                "version": value.version,
                "definition_hash": value.definition_hash,
            }
            for value in spec.feature_bindings
        ],
        "label_bindings": [
            {
                "label_id": value.label_id,
                "version": value.version,
                "schema_hash": value.schema_hash,
                "dataset_version_id": value.dataset_version_id,
            }
            for value in spec.label_bindings
        ],
        "decision_time_policy_version": spec.decision_time_policy_version,
        "time_split": spec.time_split.hash_payload(),
        "parameters": [
            {"name": value.name, "value": value.value}
            for value in spec.parameters
        ],
        "random_seed": spec.random_seed,
        "code": {
            "experiment_spec_sha": spec.code_sha,
            "factor_version_sha": factor_version.code_sha,
        },
        "environment": {
            "environment_id": spec.environment.environment_id,
            "python_version": spec.environment.python_version,
            "platform": spec.environment.platform,
            "dependency_lock_hash": spec.environment.dependency_lock_hash,
        },
        "validation": {
            "readiness_evidence_hash": spec.readiness_evidence_hash,
            "declared_metric_names": spec.metric_names,
            "report_id": validation_report.report_id,
            "report_version": validation_report.report_version,
            "report_hash": validation_report.content_hash,
            "created_at": _canonical_time(validation_report.created_at),
            "artifact_hashes": validation_report.artifact_hashes,
            "input_trust_state": validation_report.input_trust_state.value,
            "historical_evidence_eligible": (
                validation_report.historical_evidence_eligible
            ),
            "passes_promotion_gate": validation_report.passes_promotion_gate,
            "checks": [
                {
                    "name": value.name.value,
                    "outcome": value.outcome.value,
                    "evidence_hashes": value.evidence_hashes,
                    "detail": value.detail,
                    "waiver": (
                        None
                        if value.waiver is None
                        else {
                            "actor_id": value.waiver.actor_id,
                            "actor_role": value.waiver.actor_role,
                            "waived_at": _canonical_time(value.waiver.waived_at),
                            "reason": value.waiver.reason,
                            "evidence_hashes": value.waiver.evidence_hashes,
                        }
                    ),
                }
                for value in validation_report.checks
            ],
        },
    }
    manifest = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return FrozenExperimentExport(
        schema_version=_EXPORT_SCHEMA,
        run_id=run.run_id,
        manifest=manifest,
        content_hash=hashlib.sha256(manifest).hexdigest(),
    )


class ExperimentExchangeService:
    def __init__(
        self,
        *,
        exporter: ExperimentExportAdapter,
        recorder_importer: ExperimentRecorderImportAdapter,
        repository: ExperimentRunRepository,
    ) -> None:
        self._exporter = exporter
        self._recorder_importer = recorder_importer
        self._repository = repository

    def export(
        self,
        *,
        run: ExperimentRun,
        factor_version: FactorVersion,
        validation_report: ValidationReport,
        experiment_name: str,
        recorder_name: str,
    ) -> ExperimentExportReceipt:
        frozen = freeze_experiment_export(
            run=run,
            factor_version=factor_version,
            validation_report=validation_report,
        )
        return self._exporter.export(
            frozen,
            experiment_name=experiment_name,
            recorder_name=recorder_name,
        )

    def import_and_register(self, request: RecorderImportRequest) -> ExperimentRun:
        if not isinstance(request, RecorderImportRequest):
            raise TypeError("request must be a RecorderImportRequest")
        imported = self._recorder_importer.import_run(request)
        if imported.run_id != request.run_id:
            raise RecorderImportError("imported recorder returned another run_id")
        if imported.spec.content_hash != request.spec.content_hash:
            raise RecorderImportError("imported recorder returned another ExperimentSpec")
        return self._repository.save_run(imported)


__all__ = ["ExperimentExchangeService", "freeze_experiment_export"]
