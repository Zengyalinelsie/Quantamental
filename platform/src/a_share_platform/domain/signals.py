"""Immutable, approval-bound SignalSnapshot contracts.

Snapshots are portfolio inputs, not an execution interface.  They can only be
compiled from a frozen InvestmentView and exact append-only factor review
evidence approved for the requested use.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from .factor_lifecycle import (
    ApprovalDecision,
    ApprovalScope,
    FactorVersion,
)
from .factor_reviews import FactorPromotionReview
from .investment_view import InvestmentView
from .pit import DataTrustState
from .run_context import DataMode, DeploymentStage, RunContext

_SCOPE_BY_STAGE = {
    DeploymentStage.RESEARCH: ApprovalScope.RESEARCH_BACKTEST,
    DeploymentStage.SHADOW: ApprovalScope.SHADOW,
    DeploymentStage.PAPER: ApprovalScope.PAPER,
    DeploymentStage.LIMITED_LIVE: ApprovalScope.LIMITED_LIVE,
}


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _canonical_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result or any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty text")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be unique")
    return result


class SignalSnapshotUnavailable(RuntimeError):
    """Exact model/factor approval or qualified inputs are unavailable."""


@dataclass(frozen=True)
class SignalSnapshotCompileRequest:
    investment_view: InvestmentView
    factor_versions: tuple[FactorVersion, ...]
    factor_reviews: tuple[FactorPromotionReview, ...]
    approval_scope: ApprovalScope
    universe_version_id: str
    rank: int
    previous_rank: int | None
    universe_size: int
    score: Decimal
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.investment_view, InvestmentView):
            raise TypeError("investment_view must be an InvestmentView")
        factors = tuple(self.factor_versions)
        reviews = tuple(self.factor_reviews)
        if not factors or any(not isinstance(value, FactorVersion) for value in factors):
            raise ValueError("factor_versions must contain FactorVersion values")
        if not reviews or any(
            not isinstance(value, FactorPromotionReview) for value in reviews
        ):
            raise ValueError("factor_reviews must contain FactorPromotionReview values")
        factor_ids = tuple(value.factor_version_id for value in factors)
        review_factor_ids = tuple(value.factor_version_id for value in reviews)
        if len(factor_ids) != len(set(factor_ids)):
            raise ValueError("factor_version_ids must be unique")
        if len(review_factor_ids) != len(set(review_factor_ids)):
            raise ValueError("factor review targets must be unique")
        if set(factor_ids) != set(review_factor_ids):
            raise ValueError("each FactorVersion requires exactly one factor review")
        object.__setattr__(
            self,
            "factor_versions",
            tuple(sorted(factors, key=lambda value: value.factor_version_id)),
        )
        object.__setattr__(
            self,
            "factor_reviews",
            tuple(sorted(reviews, key=lambda value: value.factor_version_id)),
        )
        scope = ApprovalScope(self.approval_scope)
        object.__setattr__(self, "approval_scope", scope)
        expected_scope = _SCOPE_BY_STAGE[self.investment_view.run_context.deployment_stage]
        if scope is not expected_scope:
            raise ValueError(
                f"{self.investment_view.run_context.deployment_stage.value} run context "
                f"requires {expected_scope.value} approval scope"
            )
        _text(self.universe_version_id, "universe_version_id")
        if type(self.universe_size) is not int or self.universe_size <= 0:
            raise ValueError("universe_size must be a positive integer")
        if type(self.rank) is not int or self.rank <= 0:
            raise ValueError("rank must be a positive integer")
        if self.rank > self.universe_size:
            raise ValueError("rank cannot exceed universe_size")
        if self.previous_rank is not None:
            if type(self.previous_rank) is not int or self.previous_rank <= 0:
                raise ValueError("previous_rank must be a positive integer when present")
            if self.previous_rank > self.universe_size:
                raise ValueError("previous_rank cannot exceed universe_size")
        _decimal(self.score, "score")
        created_at = _aware(self.created_at, "created_at")
        if created_at < self.investment_view.decision_time:
            raise ValueError("created_at cannot precede decision_time")

    def hash_payload(self) -> dict[str, object]:
        return {
            "investment_view_id": self.investment_view.view_id,
            "investment_view_hash": self.investment_view.content_hash,
            "factor_versions": tuple(
                {
                    "factor_version_id": value.factor_version_id,
                    "content_hash": value.content_hash,
                }
                for value in self.factor_versions
            ),
            "factor_reviews": tuple(
                {
                    "review_id": value.review_id,
                    "content_hash": value.content_hash,
                }
                for value in self.factor_reviews
            ),
            "approval_scope": self.approval_scope.value,
            "universe_version_id": self.universe_version_id,
            "rank": self.rank,
            "previous_rank": self.previous_rank,
            "universe_size": self.universe_size,
            "score": _decimal_text(self.score),
            "created_at": _canonical_time(self.created_at),
        }


@dataclass(frozen=True)
class SignalSnapshot:
    snapshot_id: str
    security_id: str
    decision_time: datetime
    horizon_trading_days: int
    universe_version_id: str
    universe_size: int
    rank: int
    previous_rank: int | None
    score: Decimal
    expected_return: Decimal
    confidence: Decimal
    investment_view_id: str
    investment_view_hash: str
    factor_version_ids: tuple[str, ...]
    factor_version_hashes: tuple[str, ...]
    factor_review_ids: tuple[str, ...]
    factor_review_hashes: tuple[str, ...]
    dataset_version_ids: tuple[str, ...]
    feature_version_ids: tuple[str, ...]
    model_version_id: str
    run_id: str
    approval_scope: ApprovalScope
    run_context: RunContext
    trust_state: DataTrustState
    data_cutoff: datetime
    created_at: datetime
    rank_change: int | None = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "snapshot_id",
            "security_id",
            "universe_version_id",
            "investment_view_id",
            "investment_view_hash",
            "model_version_id",
            "run_id",
        ):
            _text(getattr(self, name), name)
        decision_time = _aware(self.decision_time, "decision_time")
        data_cutoff = _aware(self.data_cutoff, "data_cutoff")
        created_at = _aware(self.created_at, "created_at")
        if data_cutoff > decision_time:
            raise ValueError("data_cutoff cannot exceed decision_time")
        if created_at < decision_time:
            raise ValueError("created_at cannot precede decision_time")
        if type(self.horizon_trading_days) is not int or self.horizon_trading_days not in {
            20,
            60,
            120,
        }:
            raise ValueError("horizon_trading_days must be 20, 60, or 120")
        if type(self.universe_size) is not int or self.universe_size <= 0:
            raise ValueError("universe_size must be a positive integer")
        if type(self.rank) is not int or not 1 <= self.rank <= self.universe_size:
            raise ValueError("rank must be within universe_size")
        if self.previous_rank is not None and (
            type(self.previous_rank) is not int
            or not 1 <= self.previous_rank <= self.universe_size
        ):
            raise ValueError("previous_rank must be within universe_size when present")
        object.__setattr__(
            self,
            "rank_change",
            None if self.previous_rank is None else self.previous_rank - self.rank,
        )
        for name in ("score", "expected_return", "confidence"):
            _decimal(getattr(self, name), name)
        if not Decimal(0) <= self.confidence <= Decimal(1):
            raise ValueError("confidence must be in [0, 1]")
        for name in (
            "factor_version_ids",
            "factor_version_hashes",
            "factor_review_ids",
            "factor_review_hashes",
            "dataset_version_ids",
            "feature_version_ids",
        ):
            object.__setattr__(self, name, _unique_texts(getattr(self, name), name))
        if len(self.factor_version_ids) != len(self.factor_version_hashes):
            raise ValueError("factor version identifiers and hashes must align")
        if len(self.factor_review_ids) != len(self.factor_review_hashes):
            raise ValueError("factor review identifiers and hashes must align")
        scope = ApprovalScope(self.approval_scope)
        object.__setattr__(self, "approval_scope", scope)
        if not isinstance(self.run_context, RunContext):
            raise TypeError("run_context must be a RunContext")
        if scope is not _SCOPE_BY_STAGE[self.run_context.deployment_stage]:
            raise ValueError("approval_scope does not match run_context")
        trust = DataTrustState(self.trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw inputs cannot produce SignalSnapshot")
        if (
            self.run_context.data_mode is DataMode.STRICT_HISTORICAL
            and trust is not DataTrustState.PIT_VERIFIED
        ):
            raise ValueError("strict_historical requires pit_verified inputs")
        object.__setattr__(self, "trust_state", trust)
        object.__setattr__(self, "content_hash", _canonical_hash(self.hash_payload()))

    def hash_payload(self) -> dict[str, object]:
        return {
            "snapshot_id": self.snapshot_id,
            "security_id": self.security_id,
            "decision_time": _canonical_time(self.decision_time),
            "horizon_trading_days": self.horizon_trading_days,
            "universe_version_id": self.universe_version_id,
            "universe_size": self.universe_size,
            "rank": self.rank,
            "previous_rank": self.previous_rank,
            "score": _decimal_text(self.score),
            "expected_return": _decimal_text(self.expected_return),
            "confidence": _decimal_text(self.confidence),
            "investment_view_id": self.investment_view_id,
            "investment_view_hash": self.investment_view_hash,
            "factor_version_ids": self.factor_version_ids,
            "factor_version_hashes": self.factor_version_hashes,
            "factor_review_ids": self.factor_review_ids,
            "factor_review_hashes": self.factor_review_hashes,
            "dataset_version_ids": self.dataset_version_ids,
            "feature_version_ids": self.feature_version_ids,
            "model_version_id": self.model_version_id,
            "run_id": self.run_id,
            "approval_scope": self.approval_scope.value,
            "run_context": {
                "data_mode": self.run_context.data_mode.value,
                "deployment_stage": self.run_context.deployment_stage.value,
            },
            "trust_state": self.trust_state.value,
            "data_cutoff": _canonical_time(self.data_cutoff),
            "created_at": _canonical_time(self.created_at),
        }


class SignalSnapshotCompiler:
    """Compile one signal only when all exact approval bindings are present."""

    def compile(self, request: SignalSnapshotCompileRequest) -> SignalSnapshot:
        if not isinstance(request, SignalSnapshotCompileRequest):
            raise TypeError("request must be a SignalSnapshotCompileRequest")
        view = request.investment_view
        reviews = {value.factor_version_id: value for value in request.factor_reviews}
        for factor in request.factor_versions:
            review = reviews[factor.factor_version_id]
            approval = review.approval
            bindings = tuple(
                binding
                for binding in factor.promotion_bindings
                if binding.scope is request.approval_scope
            )
            if (
                review.factor_version_hash != factor.content_hash
                or review.factor_lifecycle_status.value != "candidate"
                or not review.scientific_gate_passed
                or approval.decision is not ApprovalDecision.APPROVED
                or approval.scope is not request.approval_scope
                or not factor.is_authorized_for(request.approval_scope)
                or not bindings
                or bindings[-1].approval_id != approval.approval_id
                or bindings[-1].approval_hash != approval.content_hash
                or bindings[-1].validation_report_id != review.validation_report_id
                or bindings[-1].validation_report_hash != review.validation_report_hash
            ):
                raise SignalSnapshotUnavailable(
                    f"exact FactorVersion {factor.factor_version_id} is not approved "
                    f"for {request.approval_scope.value}"
                )
        approved_datasets = {
            item for factor in request.factor_versions for item in factor.dataset_version_ids
        }
        approved_features = {
            item for factor in request.factor_versions for item in factor.feature_version_ids
        }
        approved_models = {
            item for factor in request.factor_versions for item in factor.model_version_ids
        }
        if not set(view.dataset_version_ids).issubset(approved_datasets):
            raise SignalSnapshotUnavailable("InvestmentView dataset version is not approved")
        if not set(view.feature_version_ids).issubset(approved_features):
            raise SignalSnapshotUnavailable("InvestmentView feature version is not approved")
        if view.model_version_id not in approved_models:
            raise SignalSnapshotUnavailable("InvestmentView model version is not approved")
        if view.code_version not in {value.code_sha for value in request.factor_versions}:
            raise SignalSnapshotUnavailable("InvestmentView code version is not approved")

        request_hash = _canonical_hash(request.hash_payload())
        return SignalSnapshot(
            snapshot_id=f"signal-snapshot:{request_hash}",
            security_id=view.security_id,
            decision_time=view.decision_time,
            horizon_trading_days=view.horizon_trading_days,
            universe_version_id=request.universe_version_id,
            universe_size=request.universe_size,
            rank=request.rank,
            previous_rank=request.previous_rank,
            score=request.score,
            expected_return=view.expected_return.point,
            confidence=view.confidence,
            investment_view_id=view.view_id,
            investment_view_hash=view.content_hash,
            factor_version_ids=tuple(
                value.factor_version_id for value in request.factor_versions
            ),
            factor_version_hashes=tuple(value.content_hash for value in request.factor_versions),
            factor_review_ids=tuple(value.review_id for value in request.factor_reviews),
            factor_review_hashes=tuple(value.content_hash for value in request.factor_reviews),
            dataset_version_ids=view.dataset_version_ids,
            feature_version_ids=view.feature_version_ids,
            model_version_id=view.model_version_id,
            run_id=view.run_id,
            approval_scope=request.approval_scope,
            run_context=view.run_context,
            trust_state=view.trust_state,
            data_cutoff=view.latest_input_available_at,
            created_at=request.created_at,
        )


__all__ = [
    "SignalSnapshot",
    "SignalSnapshotCompileRequest",
    "SignalSnapshotCompiler",
    "SignalSnapshotUnavailable",
]
