import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

from a_share_platform.application.permissions import Role
from a_share_platform.domain.factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorLifecycleEvent,
    FactorLifecycleStatus,
    FactorPromotionError,
    FactorVersion,
    PromotionApproval,
    ValidationCheck,
    ValidationCheckName,
    ValidationOutcome,
    ValidationReport,
    ValidationWaiver,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext

NOW = datetime(2026, 8, 11, 8, tzinfo=UTC)


def digest(marker: str) -> str:
    return marker * 64


def waiver() -> ValidationWaiver:
    return ValidationWaiver(
        actor_id="user:reviewer-01",
        actor_role=Role.REVIEWER.value,
        waived_at=NOW,
        reason="Capacity evidence is not material for research-only use.",
        evidence_hashes=(digest("e"),),
    )


def checks(
    *,
    failed: ValidationCheckName | None = None,
    waived: ValidationCheckName | None = None,
) -> tuple[ValidationCheck, ...]:
    values = []
    for name in ValidationCheckName:
        if name is failed:
            values.append(
                ValidationCheck(
                    name=name,
                    outcome=ValidationOutcome.FAIL,
                    evidence_hashes=(digest("f"),),
                    detail="Acceptance threshold was not met.",
                )
            )
        elif name is waived:
            values.append(
                ValidationCheck(
                    name=name,
                    outcome=ValidationOutcome.WAIVED,
                    evidence_hashes=(digest("e"),),
                    detail="Human waiver recorded.",
                    waiver=waiver(),
                )
            )
        else:
            values.append(
                ValidationCheck(
                    name=name,
                    outcome=ValidationOutcome.PASS,
                    evidence_hashes=(digest("a"),),
                    detail="Versioned metric artifact passed its declared threshold.",
                )
            )
    return tuple(values)


def report(**overrides: object) -> ValidationReport:
    values: dict[str, object] = {
        "report_id": "validation-report:quality:v1",
        "report_version": "v1",
        "factor_version_id": "factor-version:quality:v1",
        "experiment_run_id": "experiment-run:quality:001",
        "dataset_version_ids": (
            "dataset:financial-facts:pit:v1",
            "dataset:bars:pit:v1",
        ),
        "code_sha": "1" * 40,
        "artifact_hashes": (digest("b"),),
        "run_context": RunContext(
            DataMode.STRICT_HISTORICAL,
            DeploymentStage.RESEARCH,
        ),
        "input_trust_state": DataTrustState.PIT_VERIFIED,
        "checks": checks(),
        "created_at": NOW,
    }
    values.update(overrides)
    return ValidationReport(**values)  # type: ignore[arg-type]


def approval(
    validation: ValidationReport,
    *,
    scope: ApprovalScope = ApprovalScope.RESEARCH_BACKTEST,
    role: str = Role.REVIEWER.value,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
    report_hash: str | None = None,
) -> PromotionApproval:
    return PromotionApproval(
        approval_id=f"approval:quality:{scope.value}:v1",
        factor_version_id=validation.factor_version_id,
        validation_report_id=validation.report_id,
        validation_report_hash=report_hash or validation.content_hash,
        scope=scope,
        decision=decision,
        actor_id="user:reviewer-01",
        actor_role=role,
        decided_at=NOW + timedelta(minutes=5),
        reason="Reviewed the frozen evidence pack for this exact use.",
        evidence_hashes=(digest("c"),),
    )


def event(
    source: FactorLifecycleStatus,
    target: FactorLifecycleStatus,
    *,
    at: datetime = NOW,
    marker: str = "d",
) -> FactorLifecycleEvent:
    return FactorLifecycleEvent(
        event_id=f"factor-event:{source.value}:{target.value}:{marker}",
        from_status=source,
        to_status=target,
        actor_id="user:researcher-01",
        actor_role=Role.RESEARCHER.value,
        occurred_at=at,
        reason=f"Advance {source.value} to {target.value}.",
        evidence_hashes=(digest(marker),),
    )


def factor() -> FactorVersion:
    return FactorVersion(
        factor_version_id="factor-version:quality:v1",
        factor_id="factor:quality",
        semantic_version="1.0.0",
        definition_hash=digest("4"),
        code_sha="2" * 40,
        dataset_version_ids=("dataset:financial-facts:pit:v1",),
        feature_version_ids=("feature:roic:v1", "feature:accruals:v1"),
        model_version_ids=(),
        created_by="user:researcher-01",
        created_at=NOW - timedelta(days=1),
    )


def candidate() -> FactorVersion:
    value = factor()
    for source, target, offset in (
        (FactorLifecycleStatus.DRAFT, FactorLifecycleStatus.RESEARCH, 1),
        (FactorLifecycleStatus.RESEARCH, FactorLifecycleStatus.SHADOW, 2),
        (FactorLifecycleStatus.SHADOW, FactorLifecycleStatus.CANDIDATE, 3),
    ):
        value = value.transition(
            event(source, target, at=NOW + timedelta(seconds=offset), marker=str(offset))
        )
    return value


class ValidationReportTest(unittest.TestCase):
    def test_complete_strict_pit_report_is_promotion_eligible(self) -> None:
        value = report()

        self.assertTrue(value.historical_evidence_eligible)
        self.assertTrue(value.passes_promotion_gate)
        self.assertEqual(value.failed_checks, ())
        self.assertEqual(
            {item.name for item in value.checks},
            set(ValidationCheckName),
        )
        with self.assertRaises(FrozenInstanceError):
            value.report_version = "v2"  # type: ignore[misc]

    def test_failed_report_is_retained_but_cannot_pass_promotion(self) -> None:
        value = report(checks=checks(failed=ValidationCheckName.FAMA_MACBETH))

        self.assertFalse(value.passes_promotion_gate)
        self.assertEqual(
            tuple(item.name for item in value.failed_checks),
            (ValidationCheckName.FAMA_MACBETH,),
        )

    def test_pit_and_walk_forward_hard_gates_cannot_be_waived(self) -> None:
        for name in (
            ValidationCheckName.PIT_INPUT_QUALIFICATION,
            ValidationCheckName.WALK_FORWARD_OOS,
        ):
            with self.subTest(name=name), self.assertRaisesRegex(
                ValueError, "hard gate"
            ):
                ValidationCheck(
                    name=name,
                    outcome=ValidationOutcome.WAIVED,
                    evidence_hashes=(digest("e"),),
                    detail="Invalid attempt.",
                    waiver=waiver(),
                )

    def test_soft_waiver_requires_human_identity_time_reason_and_evidence(self) -> None:
        base = waiver()
        for field_name, value in (
            ("actor_id", ""),
            ("actor_role", Role.AGENT.value),
            ("waived_at", NOW.replace(tzinfo=None)),
            ("reason", ""),
            ("evidence_hashes", ()),
        ):
            with self.subTest(field=field_name), self.assertRaises(
                (TypeError, ValueError, PermissionError)
            ):
                replace(base, **{field_name: value})  # type: ignore[arg-type]

        with self.assertRaisesRegex(ValueError, "waiver"):
            ValidationCheck(
                name=ValidationCheckName.COST_CAPACITY,
                outcome=ValidationOutcome.WAIVED,
                evidence_hashes=(digest("e"),),
                detail="Missing waiver record.",
            )

    def test_current_data_is_honestly_stored_but_not_historical_evidence(self) -> None:
        current = report(
            run_context=RunContext(
                DataMode.CURRENT_RESEARCH,
                DeploymentStage.RESEARCH,
            ),
            input_trust_state=DataTrustState.NORMALIZED_CURRENT,
        )

        self.assertFalse(current.historical_evidence_eligible)
        self.assertFalse(current.passes_promotion_gate)

    def test_report_requires_every_spec_021_check_exactly_once(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing validation checks"):
            report(checks=checks()[:-1])
        with self.assertRaisesRegex(ValueError, "unique"):
            report(checks=(*checks(), checks()[0]))


class ApprovalContractTest(unittest.TestCase):
    def test_reviewer_or_administrator_can_record_a_scoped_decision(self) -> None:
        validation = report()
        for role in (Role.REVIEWER.value, Role.ADMINISTRATOR.value):
            with self.subTest(role=role):
                value = approval(validation, role=role)
                self.assertTrue(
                    value.authorizes(
                        factor_version_id=validation.factor_version_id,
                        validation_report=validation,
                        scope=ApprovalScope.RESEARCH_BACKTEST,
                    )
                )

    def test_researcher_agent_and_data_operator_have_no_factor_approval_power(self) -> None:
        validation = report()
        for role in (
            Role.RESEARCHER.value,
            Role.AGENT.value,
            Role.DATA_OPERATOR.value,
        ):
            with self.subTest(role=role), self.assertRaisesRegex(
                PermissionError, "factor promotion"
            ):
                approval(validation, role=role)

    def test_approval_is_exactly_scoped_and_bound_to_frozen_report_hash(self) -> None:
        validation = report()
        research = approval(validation, scope=ApprovalScope.RESEARCH_BACKTEST)

        self.assertTrue(
            research.authorizes(
                factor_version_id=validation.factor_version_id,
                validation_report=validation,
                scope=ApprovalScope.RESEARCH_BACKTEST,
            )
        )
        for scope in (
            ApprovalScope.SHADOW,
            ApprovalScope.PAPER,
            ApprovalScope.LIMITED_LIVE,
        ):
            self.assertFalse(
                research.authorizes(
                    factor_version_id=validation.factor_version_id,
                    validation_report=validation,
                    scope=scope,
                )
            )
        self.assertFalse(
            approval(validation, report_hash=digest("9")).authorizes(
                factor_version_id=validation.factor_version_id,
                validation_report=validation,
                scope=ApprovalScope.RESEARCH_BACKTEST,
            )
        )

    def test_rejection_is_auditable_but_never_authorizes_use(self) -> None:
        validation = report()
        rejected = approval(validation, decision=ApprovalDecision.REJECTED)

        self.assertFalse(
            rejected.authorizes(
                factor_version_id=validation.factor_version_id,
                validation_report=validation,
                scope=ApprovalScope.RESEARCH_BACKTEST,
            )
        )
        self.assertEqual(rejected.actor_id, "user:reviewer-01")
        self.assertTrue(rejected.evidence_hashes)


class FactorVersionLifecycleTest(unittest.TestCase):
    def test_lifecycle_is_sequential_and_keeps_content_identity_immutable(self) -> None:
        original = factor()
        advanced = candidate()

        self.assertEqual(advanced.status, FactorLifecycleStatus.CANDIDATE)
        self.assertEqual(len(advanced.lifecycle_events), 3)
        self.assertEqual(advanced.content_hash, original.content_hash)
        self.assertEqual(advanced.definition_hash, original.definition_hash)
        with self.assertRaises(FrozenInstanceError):
            advanced.definition_hash = digest("8")  # type: ignore[misc]

        with self.assertRaisesRegex(ValueError, "illegal factor lifecycle"):
            original.transition(
                event(
                    FactorLifecycleStatus.DRAFT,
                    FactorLifecycleStatus.PRODUCTION,
                )
            )

    def test_unvalidated_or_unapproved_candidate_cannot_become_production(self) -> None:
        value = candidate()
        promote = event(
            FactorLifecycleStatus.CANDIDATE,
            FactorLifecycleStatus.PRODUCTION,
            at=NOW + timedelta(minutes=10),
        )
        with self.assertRaisesRegex(FactorPromotionError, "ValidationReport"):
            value.transition(promote)
        with self.assertRaisesRegex(FactorPromotionError, "Approval"):
            value.transition(promote, validation_report=report())

    def test_failed_or_current_report_cannot_promote_candidate(self) -> None:
        value = candidate()
        promote = event(
            FactorLifecycleStatus.CANDIDATE,
            FactorLifecycleStatus.PRODUCTION,
            at=NOW + timedelta(minutes=10),
        )
        for validation in (
            report(checks=checks(failed=ValidationCheckName.FDR)),
            report(
                run_context=RunContext(
                    DataMode.CURRENT_RESEARCH,
                    DeploymentStage.RESEARCH,
                ),
                input_trust_state=DataTrustState.NORMALIZED_CURRENT,
            ),
        ):
            with self.subTest(report=validation.content_hash), self.assertRaisesRegex(
                FactorPromotionError, "validation"
            ):
                value.transition(
                    promote,
                    validation_report=validation,
                    approval=approval(validation),
                    scope=ApprovalScope.RESEARCH_BACKTEST,
                )

    def test_matching_reviewer_approval_promotes_and_only_authorizes_exact_scope(self) -> None:
        value = candidate()
        validation = report()
        signed = approval(validation)
        production = value.transition(
            event(
                FactorLifecycleStatus.CANDIDATE,
                FactorLifecycleStatus.PRODUCTION,
                at=NOW + timedelta(minutes=10),
            ),
            validation_report=validation,
            approval=signed,
            scope=ApprovalScope.RESEARCH_BACKTEST,
        )

        self.assertEqual(production.status, FactorLifecycleStatus.PRODUCTION)
        self.assertTrue(
            production.is_authorized_for(ApprovalScope.RESEARCH_BACKTEST)
        )
        self.assertFalse(production.is_authorized_for(ApprovalScope.PAPER))
        self.assertFalse(production.is_authorized_for(ApprovalScope.LIMITED_LIVE))
        self.assertEqual(production.content_hash, value.content_hash)

    def test_suspend_and_reactivate_requires_new_matching_approval_and_audit_event(self) -> None:
        validation = report()
        first_approval = approval(validation)
        production = candidate().transition(
            event(
                FactorLifecycleStatus.CANDIDATE,
                FactorLifecycleStatus.PRODUCTION,
                at=NOW + timedelta(minutes=10),
            ),
            validation_report=validation,
            approval=first_approval,
            scope=ApprovalScope.RESEARCH_BACKTEST,
        )
        suspended = production.transition(
            event(
                FactorLifecycleStatus.PRODUCTION,
                FactorLifecycleStatus.SUSPENDED,
                at=NOW + timedelta(minutes=20),
            )
        )

        self.assertFalse(suspended.is_authorized_for(ApprovalScope.RESEARCH_BACKTEST))
        reactivate = event(
            FactorLifecycleStatus.SUSPENDED,
            FactorLifecycleStatus.PRODUCTION,
            at=NOW + timedelta(minutes=30),
            marker="5",
        )
        with self.assertRaisesRegex(FactorPromotionError, "Approval"):
            suspended.transition(
                reactivate,
                validation_report=validation,
                scope=ApprovalScope.RESEARCH_BACKTEST,
            )

        renewed = replace(
            first_approval,
            approval_id="approval:quality:research-backtest:v2",
            decided_at=NOW + timedelta(minutes=25),
            evidence_hashes=(digest("6"),),
        )
        restored = suspended.transition(
            reactivate,
            validation_report=validation,
            approval=renewed,
            scope=ApprovalScope.RESEARCH_BACKTEST,
        )
        self.assertTrue(restored.is_authorized_for(ApprovalScope.RESEARCH_BACKTEST))
        self.assertEqual(restored.content_hash, production.content_hash)
        self.assertEqual(len(restored.lifecycle_events), len(production.lifecycle_events) + 2)

    def test_factor_approval_never_grants_broker_or_order_authority(self) -> None:
        validation = report()
        signed = approval(validation, scope=ApprovalScope.LIMITED_LIVE)

        self.assertFalse(signed.grants_account_access)
        self.assertFalse(signed.grants_order_authority)

    def test_reconstructed_production_cannot_drop_or_detach_approval_binding(self) -> None:
        validation = report()
        signed = approval(validation)
        production = candidate().transition(
            event(
                FactorLifecycleStatus.CANDIDATE,
                FactorLifecycleStatus.PRODUCTION,
                at=NOW + timedelta(minutes=10),
            ),
            validation_report=validation,
            approval=signed,
            scope=ApprovalScope.RESEARCH_BACKTEST,
        )

        with self.assertRaisesRegex(ValueError, "production transition.*binding"):
            replace(production, promotion_bindings=())
        with self.assertRaisesRegex(ValueError, "production transition.*binding"):
            replace(
                production,
                promotion_bindings=(
                    replace(
                        production.promotion_bindings[0],
                        bound_at=NOW + timedelta(minutes=11),
                    ),
                ),
            )


if __name__ == "__main__":
    unittest.main()
