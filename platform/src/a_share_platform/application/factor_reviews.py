"""Reviewer-only application service for scoped factor promotion decisions."""

from __future__ import annotations

from datetime import datetime

from a_share_platform.domain.factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorLifecycleStatus,
    FactorVersion,
    PromotionApproval,
    ValidationReport,
)
from a_share_platform.domain.factor_reviews import FactorPromotionReview
from a_share_platform.ports.factor_reviews import FactorReviewRepository

from .permissions import Permission, PermissionPolicy, Principal, Role


class FactorReviewDenied(PermissionError):
    """The principal is not a human Reviewer for this use case."""


class InvalidFactorReview(ValueError):
    """The requested decision violates evidence, scope, or lifecycle contracts."""


class FactorReviewService:
    def __init__(
        self,
        repository: FactorReviewRepository,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._permission_policy = permission_policy or PermissionPolicy.default()

    def record_review(
        self,
        *,
        factor_version: FactorVersion,
        validation_report: ValidationReport,
        approval_id: str,
        scope: ApprovalScope | str,
        decision: ApprovalDecision | str,
        principal: Principal,
        decided_at: datetime,
        reason: str,
        evidence_hashes: tuple[str, ...],
    ) -> FactorPromotionReview:
        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        review_roles = principal.roles.intersection(
            {Role.REVIEWER, Role.ADMINISTRATOR}
        )
        if not review_roles or not self._permission_policy.allows(
            principal, Permission.APPROVE_RESEARCH
        ):
            raise FactorReviewDenied(
                f"subject {principal.subject_id} has no factor review authority"
            )
        actor_role = (
            Role.REVIEWER
            if Role.REVIEWER in review_roles
            else Role.ADMINISTRATOR
        )
        if not isinstance(factor_version, FactorVersion):
            raise TypeError("factor_version must be a FactorVersion")
        if factor_version.status is not FactorLifecycleStatus.CANDIDATE:
            raise InvalidFactorReview("factor promotion review requires candidate lifecycle")
        if not isinstance(validation_report, ValidationReport):
            raise TypeError("validation_report must be a ValidationReport")
        if validation_report.factor_version_id != factor_version.factor_version_id:
            raise InvalidFactorReview("validation report targets another FactorVersion")
        selected_decision = ApprovalDecision(decision)
        if (
            selected_decision is ApprovalDecision.APPROVED
            and not validation_report.passes_promotion_gate
        ):
            raise InvalidFactorReview(
                "approval cannot override failed scientific validation"
            )
        if decided_at < validation_report.created_at:
            raise InvalidFactorReview("review decision cannot precede ValidationReport")
        approval = PromotionApproval(
            approval_id=approval_id,
            factor_version_id=factor_version.factor_version_id,
            validation_report_id=validation_report.report_id,
            validation_report_hash=validation_report.content_hash,
            scope=ApprovalScope(scope),
            decision=selected_decision,
            actor_id=principal.subject_id,
            actor_role=actor_role.value,
            decided_at=decided_at,
            reason=reason,
            evidence_hashes=evidence_hashes,
        )
        value = FactorPromotionReview.from_evidence(
            factor_version=factor_version,
            validation_report=validation_report,
            approval=approval,
        )
        return self._repository.save_review(value)

    def get_review(self, review_id: str) -> FactorPromotionReview | None:
        return self._repository.get_review(review_id)

    def list_reviews(self) -> tuple[FactorPromotionReview, ...]:
        return self._repository.list_reviews()


__all__ = [
    "FactorReviewDenied",
    "FactorReviewService",
    "InvalidFactorReview",
]
