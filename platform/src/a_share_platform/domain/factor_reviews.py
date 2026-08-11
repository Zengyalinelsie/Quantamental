"""Immutable reviewer decisions bound to frozen factor and validation evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from .factor_lifecycle import (
    ApprovalDecision,
    FactorLifecycleStatus,
    FactorVersion,
    PromotionApproval,
    ValidationReport,
)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _sha256(value: str, field_name: str) -> str:
    _text(value, field_name)
    if _SHA256.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FactorReviewConflict(RuntimeError):
    """An immutable review identifier was reused with different evidence."""


@dataclass(frozen=True)
class FactorPromotionReview:
    """Append-only audit record; it never grants broker or order authority."""

    review_id: str
    factor_version_id: str
    factor_version_hash: str
    factor_lifecycle_status: FactorLifecycleStatus
    validation_report_id: str
    validation_report_hash: str
    scientific_gate_passed: bool
    approval: PromotionApproval
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.review_id, "review_id"),
            (self.factor_version_id, "factor_version_id"),
            (self.validation_report_id, "validation_report_id"),
        ):
            _text(value, field_name)
        _sha256(self.factor_version_hash, "factor_version_hash")
        _sha256(self.validation_report_hash, "validation_report_hash")
        status = FactorLifecycleStatus(self.factor_lifecycle_status)
        object.__setattr__(self, "factor_lifecycle_status", status)
        if status is not FactorLifecycleStatus.CANDIDATE:
            raise ValueError("factor promotion review requires candidate lifecycle status")
        if type(self.scientific_gate_passed) is not bool:
            raise TypeError("scientific_gate_passed must be a boolean")
        if not isinstance(self.approval, PromotionApproval):
            raise TypeError("approval must be a PromotionApproval")
        if self.review_id != self.approval.approval_id:
            raise ValueError("review_id must equal approval_id")
        if self.factor_version_id != self.approval.factor_version_id:
            raise ValueError("review and approval target different FactorVersions")
        if self.validation_report_id != self.approval.validation_report_id:
            raise ValueError("review and approval target different ValidationReports")
        if self.validation_report_hash != self.approval.validation_report_hash:
            raise ValueError("review and approval bind different ValidationReport hashes")
        if self.approval.actor_role not in {"reviewer", "administrator"}:
            raise PermissionError(
                "factor review service requires Reviewer or Administrator authority"
            )
        if (
            self.approval.decision is ApprovalDecision.APPROVED
            and not self.scientific_gate_passed
        ):
            raise ValueError("approval cannot override a failed scientific gate")
        object.__setattr__(
            self,
            "content_hash",
            _canonical_hash(self.hash_payload()),
        )

    @classmethod
    def from_evidence(
        cls,
        *,
        factor_version: FactorVersion,
        validation_report: ValidationReport,
        approval: PromotionApproval,
    ) -> FactorPromotionReview:
        if not isinstance(factor_version, FactorVersion):
            raise TypeError("factor_version must be a FactorVersion")
        if not isinstance(validation_report, ValidationReport):
            raise TypeError("validation_report must be a ValidationReport")
        if validation_report.factor_version_id != factor_version.factor_version_id:
            raise ValueError("validation report targets another FactorVersion")
        return cls(
            review_id=approval.approval_id,
            factor_version_id=factor_version.factor_version_id,
            factor_version_hash=factor_version.content_hash,
            factor_lifecycle_status=factor_version.status,
            validation_report_id=validation_report.report_id,
            validation_report_hash=validation_report.content_hash,
            scientific_gate_passed=validation_report.passes_promotion_gate,
            approval=approval,
        )

    @property
    def grants_account_access(self) -> bool:
        return False

    @property
    def grants_order_authority(self) -> bool:
        return False

    def hash_payload(self) -> dict[str, object]:
        return {
            "review_id": self.review_id,
            "factor_version_id": self.factor_version_id,
            "factor_version_hash": self.factor_version_hash,
            "factor_lifecycle_status": self.factor_lifecycle_status.value,
            "validation_report_id": self.validation_report_id,
            "validation_report_hash": self.validation_report_hash,
            "scientific_gate_passed": self.scientific_gate_passed,
            "approval_hash": self.approval.content_hash,
        }


__all__ = ["FactorPromotionReview", "FactorReviewConflict"]
