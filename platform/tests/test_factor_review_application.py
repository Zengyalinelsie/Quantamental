import unittest
from datetime import timedelta

from a_share_platform.adapters.memory.factor_reviews import (
    InMemoryFactorReviewRepository,
)
from a_share_platform.application.factor_reviews import (
    FactorReviewDenied,
    FactorReviewService,
    InvalidFactorReview,
)
from a_share_platform.application.permissions import Principal, Role
from a_share_platform.domain.factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorLifecycleStatus,
    ValidationCheckName,
)
from tests.test_factor_lifecycle import NOW, candidate, checks, digest, factor, report


class FactorReviewServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryFactorReviewRepository()
        self.service = FactorReviewService(self.repository)
        self.reviewer = Principal("user:reviewer-01", frozenset({Role.REVIEWER}))

    def record(self, **overrides: object):
        values: dict[str, object] = {
            "factor_version": candidate(),
            "validation_report": report(),
            "approval_id": "approval:quality:research-backtest:v1",
            "scope": ApprovalScope.RESEARCH_BACKTEST,
            "decision": ApprovalDecision.APPROVED,
            "principal": self.reviewer,
            "decided_at": NOW + timedelta(minutes=5),
            "reason": "Reviewed the frozen evidence pack for this exact use.",
            "evidence_hashes": (digest("c"),),
        }
        values.update(overrides)
        return self.service.record_review(**values)  # type: ignore[arg-type]

    def test_reviewer_records_exact_scoped_approval_idempotently(self) -> None:
        stored = self.record()

        self.assertEqual(stored.factor_lifecycle_status, FactorLifecycleStatus.CANDIDATE)
        self.assertTrue(stored.scientific_gate_passed)
        self.assertEqual(stored.approval.scope, ApprovalScope.RESEARCH_BACKTEST)
        self.assertEqual(stored.approval.actor_id, self.reviewer.subject_id)
        self.assertEqual(stored.approval.actor_role, Role.REVIEWER.value)
        self.assertFalse(stored.grants_account_access)
        self.assertFalse(stored.grants_order_authority)
        self.assertEqual(self.record(), stored)
        self.assertEqual(self.service.get_review(stored.review_id), stored)
        self.assertEqual(self.service.list_reviews(), (stored,))

    def test_reviewer_and_administrator_can_review_but_other_roles_cannot(self) -> None:
        administrator = self.record(
            principal=Principal(
                "user:administrator", frozenset({Role.ADMINISTRATOR})
            ),
            approval_id="approval:administrator:v1",
        )
        self.assertEqual(
            administrator.approval.actor_role,
            Role.ADMINISTRATOR.value,
        )
        for role in (
            Role.RESEARCHER,
            Role.AGENT,
            Role.DATA_OPERATOR,
        ):
            with self.subTest(role=role), self.assertRaises(FactorReviewDenied):
                self.record(
                    principal=Principal(f"user:{role.value}", frozenset({role})),
                    approval_id=f"approval:denied:{role.value}",
                )

    def test_scientific_failure_cannot_be_approved_but_is_retained_when_rejected(self) -> None:
        failed = report(checks=checks(failed=ValidationCheckName.FAMA_MACBETH))

        with self.assertRaisesRegex(InvalidFactorReview, "scientific"):
            self.record(validation_report=failed)

        rejected = self.record(
            validation_report=failed,
            approval_id="approval:quality:rejected:v1",
            decision=ApprovalDecision.REJECTED,
        )
        self.assertFalse(rejected.scientific_gate_passed)
        self.assertEqual(rejected.approval.decision, ApprovalDecision.REJECTED)

    def test_review_requires_candidate_matching_report_and_non_backdated_decision(self) -> None:
        with self.assertRaisesRegex(InvalidFactorReview, "candidate"):
            self.record(factor_version=factor())

        with self.assertRaisesRegex(InvalidFactorReview, "another FactorVersion"):
            self.record(
                validation_report=report(factor_version_id="factor-version:other:v1")
            )
        with self.assertRaisesRegex(InvalidFactorReview, "precede"):
            self.record(decided_at=NOW - timedelta(seconds=1))

    def test_same_identifier_with_different_scope_or_decision_conflicts(self) -> None:
        self.record()
        with self.assertRaisesRegex(Exception, "immutable factor review conflict"):
            self.record(scope=ApprovalScope.SHADOW)


if __name__ == "__main__":
    unittest.main()
