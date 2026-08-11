import hashlib
import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.application.factor_qualification import (
    FactorQualificationService,
)
from a_share_platform.domain.backfill import DatasetQualityStatus
from a_share_platform.domain.experiments import ExperimentEnvironment, ExperimentRunStatus
from a_share_platform.domain.factor_lifecycle import (
    FactorLifecycleStatus,
    ValidationCheckName,
    ValidationOutcome,
)
from a_share_platform.domain.factor_qualification import (
    FactorQualificationRequest,
    FactorQualificationRoleEvidence,
    FactorQualificationSnapshot,
    FactorQualificationTarget,
    FactorRoleAvailability,
)
from a_share_platform.domain.factor_readiness import FactorDataRole
from a_share_platform.domain.pit import DataTrustState

NOW = datetime(2026, 8, 11, 12, tzinfo=UTC)
START = date(2018, 1, 1)
END = date(2025, 12, 31)


def digest(marker: str) -> str:
    return marker * 64


def request() -> FactorQualificationRequest:
    return FactorQualificationRequest(
        request_id="factor-qualification:csi800:2018-2025:v1",
        requested_universe_id="universe:csi800:pit:requested:v1",
        benchmark_id="index:000906",
        expected_entity_count=800,
        start_date=START,
        end_date=END,
        minimum_coverage=Decimal("0.98"),
        threshold_source="p4-factor-study-policy:v1",
        decision_time_policy_version="decision-time:close-plus-disclosure:v1",
        evaluated_at=NOW,
    )


def evidence(
    role: FactorDataRole,
    *,
    trust: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    quality: DatasetQualityStatus = DatasetQualityStatus.WARNED,
    rows: int = 10,
    entities: int = 10,
    start: date | None = START,
    end: date | None = END,
    availability: FactorRoleAvailability = FactorRoleAvailability.OBSERVED,
    availability_enforced: bool = False,
    lineage_complete: bool = True,
) -> FactorQualificationRoleEvidence:
    return FactorQualificationRoleEvidence(
        role=role,
        availability=availability,
        upstream_dataset_version_ids=(f"dataset:real:{role.value}:v1",) if rows else (),
        upstream_source_ids=(f"source:real:{role.value}:v1",),
        trust_state=trust,
        quality_status=quality,
        row_count=rows,
        observed_entity_count=entities,
        expected_entity_count=800,
        start_date=start,
        end_date=end,
        availability_enforced=availability_enforced,
        lineage_complete=lineage_complete,
        query_hash=hashlib.sha256(role.value.encode()).hexdigest(),
        warnings=(f"real blocker for {role.value}",),
    )


def snapshot() -> FactorQualificationSnapshot:
    roles = []
    for role in FactorDataRole:
        if role is FactorDataRole.FINANCIAL_FACT:
            roles.append(
                evidence(
                    role,
                    trust=DataTrustState.PIT_VERIFIED,
                    quality=DatasetQualityStatus.PASSED,
                    rows=12,
                    entities=2,
                    start=date(2025, 3, 31),
                    end=date(2025, 3, 31),
                    availability_enforced=False,
                )
            )
        elif role is FactorDataRole.FORWARD_RETURN_LABEL:
            roles.append(
                evidence(
                    role,
                    quality=DatasetQualityStatus.FAILED,
                    rows=0,
                    entities=0,
                    start=None,
                    end=None,
                    availability=FactorRoleAvailability.UNAVAILABLE,
                    availability_enforced=False,
                )
            )
        elif role is FactorDataRole.HISTORICAL_UNIVERSE:
            roles.append(
                evidence(
                    role,
                    rows=29600,
                    entities=800,
                    lineage_complete=False,
                )
            )
        elif role is FactorDataRole.RAW_DAILY_BAR:
            roles.append(
                evidence(
                    role,
                    rows=7177,
                    entities=30,
                    start=date(2018, 1, 1),
                    end=date(2018, 12, 31),
                )
            )
        else:
            roles.append(evidence(role))
    return FactorQualificationSnapshot(
        request=request(),
        candidate_universe_version_id=(
            "universe:000905:dataset:backfill:private-local:current:v1"
        ),
        candidate_universe_version_ids=(
            "universe:000300:dataset:backfill:private-local:current:v1",
            "universe:000905:dataset:backfill:private-local:current:v1",
        ),
        role_evidence=tuple(roles),
        observed_pit_metric_codes=(
            "income.net_profit_parent",
            "income.operating_revenue",
        ),
        feature_snapshot_counts=(
            ("feature:quality", 0),
            ("feature:valuation-expectation-gap", 0),
            ("feature:fundamental-improvement", 0),
        ),
    )


def targets() -> tuple[FactorQualificationTarget, ...]:
    return (
        FactorQualificationTarget(
            factor_key="quality",
            factor_id="factor:quality",
            factor_version_id="factor-version:quality:p4-qualification:v1",
            feature_id="feature:quality",
            feature_version="v0",
            definition_hash=digest("a"),
            required_metric_codes=(
                "balance.total_assets",
                "cashflow.operating_cash_flow",
                "income.net_profit_parent",
                "income.operating_revenue",
            ),
        ),
        FactorQualificationTarget(
            factor_key="valuation_expectation_gap",
            factor_id="factor:valuation-expectation-gap",
            factor_version_id=(
                "factor-version:valuation-expectation-gap:p4-qualification:v1"
            ),
            feature_id="feature:valuation-expectation-gap",
            feature_version="v0",
            definition_hash=digest("b"),
            required_metric_codes=(
                "balance.total_equity",
                "income.net_profit_parent",
            ),
        ),
        FactorQualificationTarget(
            factor_key="fundamental_improvement",
            factor_id="factor:fundamental-improvement",
            factor_version_id=(
                "factor-version:fundamental-improvement:p4-qualification:v1"
            ),
            feature_id="feature:fundamental-improvement",
            feature_version="v0",
            definition_hash=digest("c"),
            required_metric_codes=(
                "income.net_profit_parent",
                "income.operating_revenue",
            ),
        ),
    )


def environment() -> ExperimentEnvironment:
    return ExperimentEnvironment(
        environment_id="environment:p4-qualification:local:v1",
        python_version="3.12.13",
        platform="macos-arm64",
        dependency_lock_hash=digest("d"),
    )


class Source:
    def __init__(self) -> None:
        self.calls = 0

    def inspect(
        self,
        value: FactorQualificationRequest,
        selected_targets: tuple[FactorQualificationTarget, ...],
    ) -> FactorQualificationSnapshot:
        self.calls += 1
        self.request = value
        self.targets = selected_targets
        return snapshot()


class Repository:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    def save(self, value):  # type: ignore[no-untyped-def]
        existing = self.values.get(value.audit_id)
        if existing is not None and existing != value:
            raise RuntimeError("immutable audit conflict")
        self.values[value.audit_id] = value
        return existing is None


class FactorQualificationAuditTest(unittest.TestCase):
    def service(self) -> tuple[FactorQualificationService, Source, Repository]:
        source = Source()
        repository = Repository()
        return FactorQualificationService(source, repository), source, repository

    def test_real_insufficiency_builds_three_failed_runs_without_scores_or_metrics(self) -> None:
        service, _, _ = self.service()

        plan = service.evaluate(
            request=request(),
            targets=targets(),
            code_sha="1" * 40,
            environment=environment(),
        )

        self.assertEqual(len(plan.audits), 3)
        self.assertEqual({item.target.factor_key for item in plan.audits}, {
            "quality",
            "valuation_expectation_gap",
            "fundamental_improvement",
        })
        for audit in plan.audits:
            with self.subTest(factor=audit.target.factor_key):
                self.assertFalse(audit.readiness.permitted)
                self.assertEqual(audit.experiment_run.status, ExperimentRunStatus.FAILED)
                self.assertEqual(audit.experiment_run.metrics, ())
                self.assertTrue(audit.experiment_run.spec.historical_evidence_eligible)
                self.assertEqual(audit.factor_version.status, FactorLifecycleStatus.DRAFT)
                self.assertFalse(audit.validation_report.passes_promotion_gate)
                self.assertEqual(
                    next(
                        check
                        for check in audit.validation_report.checks
                        if check.name is ValidationCheckName.PIT_INPUT_QUALIFICATION
                    ).outcome,
                    ValidationOutcome.FAIL,
                )
                self.assertTrue(
                    all(
                        check.outcome is not ValidationOutcome.PASS
                        for check in audit.validation_report.checks
                    )
                )
                document = json.loads(audit.artifact_payload)
                self.assertFalse(document["factor_scores_computed"])
                self.assertFalse(document["scientific_metrics_computed"])
                self.assertFalse(document["readiness_permitted"])
                self.assertEqual(document["observed_pit_facts"], 12)

    def test_zero_label_dataset_is_explicit_unavailable_and_contains_no_label_rows(self) -> None:
        service, _, _ = self.service()

        plan = service.evaluate(
            request=request(),
            targets=targets(),
            code_sha="1" * 40,
            environment=environment(),
        )
        label = next(
            value
            for value in plan.role_datasets
            if value.role is FactorDataRole.FORWARD_RETURN_LABEL
        )
        manifest = json.loads(label.manifest)

        self.assertEqual(manifest["role"], "forward_return_label")
        self.assertEqual(manifest["row_count"], 0)
        self.assertEqual(manifest["status"], "unavailable")
        self.assertEqual(manifest["trust_state"], "normalized_current")
        self.assertEqual(manifest["observations"], [])
        self.assertTrue(manifest["query_hash"])
        self.assertTrue(manifest["decision_time_policy_hash"])
        self.assertNotIn("label_value", manifest)

    def test_ensure_is_append_only_idempotent_and_never_promotes(self) -> None:
        service, source, repository = self.service()
        arguments = {
            "request": request(),
            "targets": targets(),
            "code_sha": "1" * 40,
            "environment": environment(),
        }

        first = service.ensure(**arguments)  # type: ignore[arg-type]
        second = service.ensure(**arguments)  # type: ignore[arg-type]

        self.assertTrue(first.writes_performed)
        self.assertFalse(second.writes_performed)
        self.assertEqual(len(repository.values), 3)
        self.assertEqual(source.calls, 2)
        self.assertTrue(
            all(
                audit.factor_version.status is FactorLifecycleStatus.DRAFT
                for audit in second.plan.audits
            )
        )

    def test_missing_role_or_any_permitted_preflight_fails_closed(self) -> None:
        incomplete = snapshot()
        with self.assertRaisesRegex(ValueError, "required role"):
            FactorQualificationSnapshot(
                request=incomplete.request,
                candidate_universe_version_id=incomplete.candidate_universe_version_id,
                candidate_universe_version_ids=incomplete.candidate_universe_version_ids,
                role_evidence=incomplete.role_evidence[:-1],
                observed_pit_metric_codes=incomplete.observed_pit_metric_codes,
                feature_snapshot_counts=incomplete.feature_snapshot_counts,
            )


if __name__ == "__main__":
    unittest.main()
