"""Build and persist honest failed P4 factor qualification evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta

from a_share_platform.domain.experiments import (
    ExperimentArtifact,
    ExperimentEnvironment,
    ExperimentFailure,
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
from a_share_platform.domain.factor_qualification import (
    FactorQualificationAudit,
    FactorQualificationRequest,
    FactorQualificationRoleDataset,
    FactorQualificationSnapshot,
    FactorQualificationTarget,
    FactorRoleAvailability,
)
from a_share_platform.domain.factor_readiness import (
    FactorDataAvailabilityPolicy,
    FactorDataBinding,
    FactorDataRequirement,
    FactorDataRole,
    FactorStudyPreflight,
    FactorStudyReadiness,
    FactorStudySpec,
)
from a_share_platform.domain.governance import DatasetVersion
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from a_share_platform.ports.factor_qualification import (
    FactorQualificationRepository,
    FactorQualificationSource,
)

_ROLE_SCHEMA_VERSION = "p4-factor-qualification-role:v1"
_AUDIT_VERSION = "p4-factor-qualification-audit:v1"
_EXPECTED_FACTORS = frozenset(
    {"quality", "valuation_expectation_gap", "fundamental_improvement"}
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _availability_policy(role: FactorDataRole) -> FactorDataAvailabilityPolicy:
    if role is FactorDataRole.FORWARD_RETURN_LABEL:
        return FactorDataAvailabilityPolicy.LABEL_OUTCOME_ONLY
    return FactorDataAvailabilityPolicy.DECISION_TIME_CUTOFF


@dataclass(frozen=True)
class FactorQualificationPlan:
    snapshot: FactorQualificationSnapshot
    role_datasets: tuple[FactorQualificationRoleDataset, ...]
    audits: tuple[FactorQualificationAudit, ...]


@dataclass(frozen=True)
class FactorQualificationOutcome:
    plan: FactorQualificationPlan
    writes_performed: bool


class FactorQualificationService:
    """Qualify existing data; this service never computes a factor value or IC."""

    def __init__(
        self,
        source: FactorQualificationSource,
        repository: FactorQualificationRepository,
    ) -> None:
        self._source = source
        self._repository = repository

    def evaluate(
        self,
        *,
        request: FactorQualificationRequest,
        targets: tuple[FactorQualificationTarget, ...],
        code_sha: str,
        environment: ExperimentEnvironment,
    ) -> FactorQualificationPlan:
        if not isinstance(request, FactorQualificationRequest):
            raise TypeError("request must be a FactorQualificationRequest")
        selected = tuple(targets)
        if any(not isinstance(value, FactorQualificationTarget) for value in selected):
            raise TypeError("targets must contain FactorQualificationTarget values")
        keys = {value.factor_key for value in selected}
        if keys != _EXPECTED_FACTORS or len(selected) != len(keys):
            raise ValueError("qualification requires exactly the three P4 factor targets")
        if not isinstance(environment, ExperimentEnvironment):
            raise TypeError("environment must be an ExperimentEnvironment")

        snapshot = self._source.inspect(request, selected)
        if snapshot.request != request:
            raise ValueError("qualification source returned another request")
        role_datasets = self._role_datasets(snapshot)
        audits = tuple(
            self._audit(
                snapshot=snapshot,
                target=target,
                role_datasets=role_datasets,
                code_sha=code_sha,
                environment=environment,
            )
            for target in sorted(selected, key=lambda value: value.factor_key)
        )
        return FactorQualificationPlan(snapshot, role_datasets, audits)

    def ensure(
        self,
        *,
        request: FactorQualificationRequest,
        targets: tuple[FactorQualificationTarget, ...],
        code_sha: str,
        environment: ExperimentEnvironment,
    ) -> FactorQualificationOutcome:
        plan = self.evaluate(
            request=request,
            targets=targets,
            code_sha=code_sha,
            environment=environment,
        )
        created = tuple(self._repository.save(value) for value in plan.audits)
        return FactorQualificationOutcome(plan=plan, writes_performed=any(created))

    @staticmethod
    def _role_datasets(
        snapshot: FactorQualificationSnapshot,
    ) -> tuple[FactorQualificationRoleDataset, ...]:
        values = []
        request = snapshot.request
        for evidence in snapshot.role_evidence:
            document: dict[str, object] = {
                "schema_version": _ROLE_SCHEMA_VERSION,
                "request_id": request.request_id,
                "snapshot_hash": snapshot.content_hash,
                "role": evidence.role.value,
                "status": (
                    "unavailable"
                    if evidence.availability is FactorRoleAvailability.UNAVAILABLE
                    else "observed"
                ),
                "trust_state": evidence.trust_state.value,
                "quality_status": evidence.quality_status.value,
                "row_count": evidence.row_count,
                "observed_entity_count": evidence.observed_entity_count,
                "expected_entity_count": evidence.expected_entity_count,
                "coverage_ratio": str(evidence.coverage_ratio),
                "start_date": (
                    None if evidence.start_date is None else evidence.start_date.isoformat()
                ),
                "end_date": (
                    None if evidence.end_date is None else evidence.end_date.isoformat()
                ),
                "availability_enforced": evidence.availability_enforced,
                "lineage_complete": evidence.lineage_complete,
                "upstream_dataset_version_ids": evidence.upstream_dataset_version_ids,
                "upstream_source_ids": evidence.upstream_source_ids,
                "query_hash": evidence.query_hash,
                "decision_time_policy_version": request.decision_time_policy_version,
                "decision_time_policy_hash": request.decision_time_policy_hash,
                "warnings": evidence.warnings,
                "observations": [],
                "observation_payload_persisted": False,
            }
            manifest = _canonical_bytes(document)
            content_hash = _digest(manifest)
            dataset = DatasetVersion(
                dataset_version_id=(
                    f"dataset:p4-qualification:{evidence.role.value}:"
                    f"{content_hash[:20]}:v1"
                ),
                content_hash=f"sha256:{content_hash}",
                created_at=request.evaluated_at,
                schema_version=_ROLE_SCHEMA_VERSION,
            )
            values.append(
                FactorQualificationRoleDataset(
                    role=evidence.role,
                    dataset=dataset,
                    manifest=manifest,
                )
            )
        return tuple(sorted(values, key=lambda value: value.role.value))

    def _audit(
        self,
        *,
        snapshot: FactorQualificationSnapshot,
        target: FactorQualificationTarget,
        role_datasets: tuple[FactorQualificationRoleDataset, ...],
        code_sha: str,
        environment: ExperimentEnvironment,
    ) -> FactorQualificationAudit:
        request = snapshot.request
        readiness = self._readiness(snapshot, target, role_datasets)
        if readiness.permitted:
            raise ValueError(
                "failure-only qualification service cannot persist a permitted study"
            )
        dataset_ids = tuple(value.dataset.dataset_version_id for value in role_datasets)
        label_dataset = next(
            value.dataset
            for value in role_datasets
            if value.role is FactorDataRole.FORWARD_RETURN_LABEL
        )
        factor_version = FactorVersion(
            factor_version_id=target.factor_version_id,
            factor_id=target.factor_id,
            semantic_version="0.0.0-qualification",
            definition_hash=target.definition_hash,
            code_sha=code_sha,
            dataset_version_ids=dataset_ids,
            feature_version_ids=(f"{target.feature_id}:{target.feature_version}",),
            model_version_ids=(),
            created_by="system:factor-qualification-audit",
            created_at=request.evaluated_at,
        )
        evidence_document = self._artifact_document(
            snapshot=snapshot,
            target=target,
            role_datasets=role_datasets,
            readiness=readiness,
            code_sha=code_sha,
            environment=environment,
        )
        artifact_payload = _canonical_bytes(evidence_document)
        artifact_hash = _digest(artifact_payload)
        suffix = artifact_hash[:20]
        artifact_id = f"artifact:p4-factor-qualification:{target.factor_key}:{suffix}"
        experiment_spec = ExperimentSpec(
            spec_id=f"experiment-spec:p4-qualification:{target.factor_key}:{suffix}",
            research_question=(
                f"Can {target.factor_key} be qualified on the requested CSI800 "
                "2018-2025 PIT panel?"
            ),
            run_context=RunContext(
                DataMode.STRICT_HISTORICAL,
                DeploymentStage.RESEARCH,
            ),
            decision_time_policy_version=request.decision_time_policy_version,
            readiness_evidence_hash=artifact_hash,
            universe_version_id=snapshot.candidate_universe_version_id,
            dataset_version_ids=dataset_ids,
            feature_bindings=(
                FeatureVersionBinding(
                    feature_id=target.feature_id,
                    version=target.feature_version,
                    definition_hash=target.definition_hash,
                ),
            ),
            label_bindings=(
                LabelVersionBinding(
                    label_id="label:forward-return-20d",
                    version="unavailable:p4-qualification:v1",
                    schema_hash=_digest(
                        _canonical_bytes(
                            {
                                "label_id": "label:forward-return-20d",
                                "horizon_sessions": 20,
                                "unit": "ratio",
                                "row_count": 0,
                                "status": "unavailable",
                            }
                        )
                    ),
                    dataset_version_id=label_dataset.dataset_version_id,
                ),
            ),
            time_split=self._time_split(request.start_date, request.end_date),
            code_sha=code_sha,
            parameters=(
                ExperimentParameter("audit_version", _AUDIT_VERSION),
                ExperimentParameter("minimum_coverage", str(request.minimum_coverage)),
                ExperimentParameter("qualification_outcome", "failed"),
                ExperimentParameter("requested_universe", request.requested_universe_id),
            ),
            random_seed=0,
            environment=environment,
            metric_names=("ic", "rank_ic"),
        )
        run_id = f"experiment-run:p4-qualification:{target.factor_key}:{suffix}"
        experiment_run = ExperimentRun(
            run_id=run_id,
            spec=experiment_spec,
            status=ExperimentRunStatus.FAILED,
            started_at=request.evaluated_at,
            finished_at=request.evaluated_at,
            metrics=(),
            artifacts=(
                ExperimentArtifact(
                    artifact_id=artifact_id,
                    kind="factor-qualification-audit",
                    media_type="application/json",
                    content_hash=artifact_hash,
                ),
            ),
            failure=ExperimentFailure(
                stage="pit-qualification",
                error_type="FactorStudyNotReady",
                message=" | ".join(readiness.blockers),
                occurred_at=request.evaluated_at,
                retryable=False,
            ),
        )
        checks = tuple(
            ValidationCheck(
                name=name,
                outcome=ValidationOutcome.FAIL,
                evidence_hashes=(artifact_hash,),
                detail=(
                    "PIT input qualification failed; see immutable audit artifact."
                    if name is ValidationCheckName.PIT_INPUT_QUALIFICATION
                    else "Not executed because PIT qualification failed; no metric was computed."
                ),
            )
            for name in ValidationCheckName
        )
        lowest_trust = (
            DataTrustState.PIT_VERIFIED
            if all(
                value.trust_state is DataTrustState.PIT_VERIFIED
                for value in snapshot.role_evidence
            )
            else DataTrustState.NORMALIZED_CURRENT
        )
        validation_report = ValidationReport(
            report_id=f"validation-report:p4-qualification:{target.factor_key}:{suffix}",
            report_version="p4-qualification:v1",
            factor_version_id=target.factor_version_id,
            experiment_run_id=run_id,
            dataset_version_ids=dataset_ids,
            code_sha=code_sha,
            artifact_hashes=(artifact_hash,),
            run_context=experiment_spec.run_context,
            input_trust_state=lowest_trust,
            checks=checks,
            created_at=request.evaluated_at,
        )
        audit_id = f"factor-qualification-audit:{target.factor_key}:{suffix}"
        return FactorQualificationAudit(
            audit_id=audit_id,
            target=target,
            snapshot=snapshot,
            role_datasets=role_datasets,
            readiness=readiness,
            factor_version=factor_version,
            experiment_run=experiment_run,
            validation_report=validation_report,
            artifact_id=artifact_id,
            artifact_hash=artifact_hash,
            artifact_payload=artifact_payload,
            created_at=request.evaluated_at,
        )

    @staticmethod
    def _readiness(
        snapshot: FactorQualificationSnapshot,
        target: FactorQualificationTarget,
        role_datasets: tuple[FactorQualificationRoleDataset, ...],
    ) -> FactorStudyReadiness:
        request = snapshot.request
        requirements = tuple(
            FactorDataRequirement(
                role=role,
                minimum_coverage=request.minimum_coverage,
                threshold_source=request.threshold_source,
                availability_policy=_availability_policy(role),
            )
            for role in FactorDataRole
        )
        datasets = {value.role: value.dataset for value in role_datasets}
        bindings = tuple(
            FactorDataBinding(
                role=evidence.role,
                dataset_version_id=datasets[evidence.role].dataset_version_id,
                trust_state=evidence.trust_state,
                quality_status=evidence.quality_status,
                coverage_ratio=evidence.coverage_ratio,
                start_date=evidence.start_date or request.start_date,
                end_date=evidence.end_date or request.end_date,
                availability_policy=_availability_policy(evidence.role),
                availability_enforced=evidence.availability_enforced,
                lineage_complete=evidence.lineage_complete,
                warnings=evidence.warnings,
            )
            for evidence in snapshot.role_evidence
        )
        result = FactorStudyPreflight().evaluate(
            FactorStudySpec(
                study_id=f"factor-study:{target.factor_key}:csi800:2018-2025:v1",
                run_context=RunContext(
                    DataMode.STRICT_HISTORICAL,
                    DeploymentStage.RESEARCH,
                ),
                universe_version_id=snapshot.candidate_universe_version_id,
                benchmark_id=request.benchmark_id,
                start_date=request.start_date,
                end_date=request.end_date,
                decision_time_policy_version=request.decision_time_policy_version,
                requirements=requirements,
                created_at=request.evaluated_at,
            ),
            bindings,
        )
        blockers = set(result.blockers)
        blockers.add(
            "requested CSI800 has no single pit_verified historical UniverseVersion; "
            f"candidate={snapshot.candidate_universe_version_id}"
        )
        missing_metrics = set(target.required_metric_codes).difference(
            snapshot.observed_pit_metric_codes
        )
        if missing_metrics:
            blockers.add(
                "missing required PIT metric codes: " + ", ".join(sorted(missing_metrics))
            )
        feature_count = snapshot.feature_snapshot_count(target.feature_id)
        if feature_count == 0:
            blockers.add(f"no persisted FeatureSnapshot for {target.feature_id}")
        return FactorStudyReadiness(
            study_id=result.study_id,
            evaluated_at=result.evaluated_at,
            permitted=False,
            blockers=tuple(sorted(blockers)),
            warnings=result.warnings,
            bound_dataset_version_ids=result.bound_dataset_version_ids,
        )

    @staticmethod
    def _artifact_document(
        *,
        snapshot: FactorQualificationSnapshot,
        target: FactorQualificationTarget,
        role_datasets: tuple[FactorQualificationRoleDataset, ...],
        readiness: FactorStudyReadiness,
        code_sha: str,
        environment: ExperimentEnvironment,
    ) -> dict[str, object]:
        financial = next(
            value
            for value in snapshot.role_evidence
            if value.role is FactorDataRole.FINANCIAL_FACT
        )
        return {
            "schema_version": _AUDIT_VERSION,
            "factor_key": target.factor_key,
            "factor_id": target.factor_id,
            "factor_version_id": target.factor_version_id,
            "factor_definition_hash": target.definition_hash,
            "feature_id": target.feature_id,
            "feature_version": target.feature_version,
            "requested_universe_id": snapshot.request.requested_universe_id,
            "candidate_universe_version_id": snapshot.candidate_universe_version_id,
            "candidate_universe_version_ids": snapshot.candidate_universe_version_ids,
            "study_window": {
                "start_date": snapshot.request.start_date.isoformat(),
                "end_date": snapshot.request.end_date.isoformat(),
            },
            "evaluated_at": snapshot.request.evaluated_at.isoformat(),
            "decision_time_policy_version": (
                snapshot.request.decision_time_policy_version
            ),
            "decision_time_policy_hash": (
                snapshot.request.decision_time_policy_hash
            ),
            "snapshot_hash": snapshot.content_hash,
            "role_dataset_version_ids": {
                value.role.value: value.dataset.dataset_version_id
                for value in role_datasets
            },
            "roles": [value.hash_payload() for value in snapshot.role_evidence],
            "observed_pit_facts": financial.row_count,
            "observed_pit_metric_codes": snapshot.observed_pit_metric_codes,
            "required_metric_codes": target.required_metric_codes,
            "feature_snapshot_count": snapshot.feature_snapshot_count(target.feature_id),
            "readiness_permitted": readiness.permitted,
            "readiness_blockers": readiness.blockers,
            "readiness_warnings": readiness.warnings,
            "requested_run_context": {
                "data_mode": DataMode.STRICT_HISTORICAL.value,
                "deployment_stage": DeploymentStage.RESEARCH.value,
                "structural_historical_evidence_eligible_is_not_a_readiness_pass": True,
            },
            "factor_scores_computed": False,
            "scientific_metrics_computed": False,
            "promotion_permitted": False,
            "research_labels_inserted": 0,
            "code_sha": code_sha,
            "environment": {
                "environment_id": environment.environment_id,
                "python_version": environment.python_version,
                "platform": environment.platform,
                "dependency_lock_hash": environment.dependency_lock_hash,
            },
        }

    @staticmethod
    def _time_split(start_date: date, end_date: date) -> ExperimentTimeSplit:
        train_end = date(2022, 1, 1)
        validation_end = date(2024, 1, 1)
        test_end = end_date + timedelta(days=1)
        if not start_date < train_end < validation_end < test_end:
            raise ValueError("P4 qualification window cannot form the frozen split")
        return ExperimentTimeSplit(
            train_start=start_date,
            train_end_exclusive=train_end,
            validation_start=train_end,
            validation_end_exclusive=validation_end,
            test_start=validation_end,
            test_end_exclusive=test_end,
            version="p4-factor-qualification-split:v1",
        )


__all__ = [
    "FactorQualificationOutcome",
    "FactorQualificationPlan",
    "FactorQualificationService",
]
