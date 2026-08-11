"""Pure multiple-testing and temporal-validation contracts for P4-W04.

This module produces deterministic research artifacts.  It does not perform
model promotion and never relabels normalized-current inputs as historical
evidence.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from .pit import DataTrustState
from .run_context import DataMode


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _probability(value: float, field_name: str, *, allow_zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    result = float(value)
    lower_valid = result >= 0 if allow_zero else result > 0
    if not math.isfinite(result) or not lower_valid or result > 1:
        boundary = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{field_name} must be in {boundary}")
    return result


def _present_p_value(value: float | None) -> float:
    if value is None:
        raise AssertionError("complete hypothesis unexpectedly contains a missing p-value")
    return value


class ValidationCalculationStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


class ValidationScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class HypothesisPValue:
    hypothesis_id: str
    p_value: float | None
    p_value_version_id: str
    data_mode: DataMode
    trust_state: DataTrustState
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.hypothesis_id, "hypothesis_id")
        _text(self.p_value_version_id, "p_value_version_id")
        if self.p_value is not None:
            object.__setattr__(
                self,
                "p_value",
                _probability(self.p_value, "p_value", allow_zero=True),
            )
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw p-values cannot enter multiple testing")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical p-values must be pit_verified")
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if self.p_value is None:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("available p-value cannot carry missing_reason")


@dataclass(frozen=True)
class BHFamilySpec:
    family_id: str
    family_version: str
    alpha: float
    minimum_hypotheses: int
    method_version: str
    tie_break_version: str

    def __post_init__(self) -> None:
        for name in (
            "family_id",
            "family_version",
            "method_version",
            "tie_break_version",
        ):
            _text(getattr(self, name), name)
        object.__setattr__(self, "alpha", _probability(self.alpha, "alpha", allow_zero=False))
        if type(self.minimum_hypotheses) is not int or self.minimum_hypotheses < 2:
            raise ValueError("minimum_hypotheses must be an integer >= 2")


@dataclass(frozen=True)
class BHDecision:
    hypothesis_id: str
    rank: int
    p_value: float
    critical_value: float
    adjusted_p_value: float
    rejected: bool


@dataclass(frozen=True)
class BHFamilyResult:
    status: ValidationCalculationStatus
    family_id: str
    family_version: str
    alpha: float
    method_version: str
    tie_break_version: str
    decisions: tuple[BHDecision, ...]
    rejected_hypothesis_ids: tuple[str, ...]
    missing_hypothesis_ids: tuple[str, ...]
    input_p_value_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: ValidationScientificStatus


def _warnings(mode: DataMode) -> tuple[str, ...]:
    if mode is DataMode.CURRENT_RESEARCH:
        return ("current_research validation is diagnostic and not a historical result",)
    return ()


def _validate_p_value_context(
    values: tuple[HypothesisPValue, ...],
    mode: DataMode,
) -> None:
    identifiers = tuple(value.hypothesis_id for value in values)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("hypothesis_id values must be unique within a family")
    versions = {value.p_value_version_id for value in values}
    if len(versions) > 1:
        raise ValueError("multiple-testing family must freeze one p-value version")
    for value in values:
        if mode is DataMode.STRICT_HISTORICAL and value.trust_state is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical family requires pit_verified p-values")
        if value.data_mode is not mode:
            raise PermissionError("current p-values cannot be relabelled as historical results")


def benjamini_hochberg(
    hypotheses: Sequence[HypothesisPValue],
    *,
    spec: BHFamilySpec,
    data_mode: DataMode,
) -> BHFamilyResult:
    """Apply deterministic Benjamini-Hochberg step-up control to one frozen family."""

    if not isinstance(spec, BHFamilySpec):
        raise TypeError("spec must be BHFamilySpec")
    values = tuple(hypotheses)
    if any(not isinstance(value, HypothesisPValue) for value in values):
        raise TypeError("hypotheses must contain HypothesisPValue values")
    mode = DataMode(data_mode)
    _validate_p_value_context(values, mode)
    versions = tuple(sorted({value.p_value_version_id for value in values}))
    missing = tuple(sorted(value.hypothesis_id for value in values if value.p_value is None))
    reason: str | None = None
    decisions: tuple[BHDecision, ...] = ()
    rejected: tuple[str, ...] = ()
    if len(values) < spec.minimum_hypotheses:
        reason = (
            f"family_size={len(values)} is below "
            f"minimum_hypotheses={spec.minimum_hypotheses}"
        )
    elif missing:
        reason = "missing p-values make the frozen multiple-testing family unavailable"
    else:
        ranked = tuple(
            sorted(
                values,
                key=lambda value: (
                    _present_p_value(value.p_value),
                    value.hypothesis_id,
                ),
            )
        )
        family_size = len(ranked)
        largest_rejected_rank = 0
        for rank, value in enumerate(ranked, start=1):
            assert value.p_value is not None
            if value.p_value <= spec.alpha * rank / family_size:
                largest_rejected_rank = rank
        adjusted = [0.0] * family_size
        running_minimum = 1.0
        for index in range(family_size - 1, -1, -1):
            p_value = ranked[index].p_value
            assert p_value is not None
            candidate = min(1.0, p_value * family_size / (index + 1))
            running_minimum = min(running_minimum, candidate)
            adjusted[index] = running_minimum
        decisions = tuple(
            BHDecision(
                hypothesis_id=value.hypothesis_id,
                rank=rank,
                p_value=_present_p_value(value.p_value),
                critical_value=spec.alpha * rank / family_size,
                adjusted_p_value=adjusted[rank - 1],
                rejected=rank <= largest_rejected_rank,
            )
            for rank, value in enumerate(ranked, start=1)
        )
        rejected = tuple(value.hypothesis_id for value in decisions if value.rejected)
    return BHFamilyResult(
        status=(
            ValidationCalculationStatus.QUANTIFIED
            if decisions
            else ValidationCalculationStatus.UNAVAILABLE
        ),
        family_id=spec.family_id,
        family_version=spec.family_version,
        alpha=spec.alpha,
        method_version=spec.method_version,
        tie_break_version=spec.tie_break_version,
        decisions=decisions,
        rejected_hypothesis_ids=rejected,
        missing_hypothesis_ids=missing,
        input_p_value_version_ids=versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=ValidationScientificStatus.NOT_EVALUATED,
    )


@dataclass(frozen=True)
class WalkForwardSample:
    sample_id: str
    session_index: int
    label_end_session_index: int
    feature_version_id: str
    label_version_id: str
    data_mode: DataMode
    feature_trust_state: DataTrustState
    label_trust_state: DataTrustState
    available: bool
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("sample_id", "feature_version_id", "label_version_id"):
            _text(getattr(self, name), name)
        for name in ("session_index", "label_end_session_index"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.label_end_session_index <= self.session_index:
            raise ValueError("label_end_session_index must follow session_index")
        mode = DataMode(self.data_mode)
        feature_trust = DataTrustState(self.feature_trust_state)
        label_trust = DataTrustState(self.label_trust_state)
        if DataTrustState.RAW in {feature_trust, label_trust}:
            raise ValueError("raw samples cannot enter walk-forward validation")
        if mode is DataMode.STRICT_HISTORICAL and {
            feature_trust,
            label_trust,
        } != {DataTrustState.PIT_VERIFIED}:
            raise PermissionError("strict_historical split samples must be pit_verified")
        if type(self.available) is not bool:
            raise TypeError("available must be a boolean")
        if not self.available:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("available sample cannot carry missing_reason")
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "feature_trust_state", feature_trust)
        object.__setattr__(self, "label_trust_state", label_trust)


@dataclass(frozen=True)
class WalkForwardSpec:
    initial_training_sessions: int
    test_sessions: int
    step_sessions: int
    horizon_sessions: int
    purge_sessions: int
    embargo_sessions: int
    minimum_training_samples: int
    split_version: str

    def __post_init__(self) -> None:
        for name in (
            "initial_training_sessions",
            "test_sessions",
            "step_sessions",
            "horizon_sessions",
            "minimum_training_samples",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("purge_sessions", "embargo_sessions"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.initial_training_sessions < self.minimum_training_samples:
            raise ValueError("initial_training_sessions must cover minimum_training_samples")
        if self.step_sessions < self.test_sessions + self.embargo_sessions:
            raise ValueError("step_sessions must cover test_sessions + embargo_sessions")
        _text(self.split_version, "split_version")


@dataclass(frozen=True)
class WalkForwardFold:
    fold_index: int
    train_candidate_end_session_index: int
    purge_cutoff_session_index: int
    test_start_session_index: int
    test_end_session_index: int
    embargo_start_session_index: int | None
    embargo_end_session_index: int | None
    training_sample_ids: tuple[str, ...]
    purged_sample_ids: tuple[str, ...]
    test_sample_ids: tuple[str, ...]
    embargoed_sample_ids: tuple[str, ...]


@dataclass(frozen=True)
class WalkForwardResult:
    status: ValidationCalculationStatus
    folds: tuple[WalkForwardFold, ...]
    split_version: str
    horizon_sessions: int
    purge_sessions: int
    embargo_sessions: int
    feature_version_ids: tuple[str, ...]
    label_version_ids: tuple[str, ...]
    missing_sample_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: ValidationScientificStatus


def _validate_walk_forward_context(
    samples: tuple[WalkForwardSample, ...],
    mode: DataMode,
    spec: WalkForwardSpec,
) -> tuple[WalkForwardSample, ...]:
    ordered = tuple(sorted(samples, key=lambda value: value.session_index))
    sample_ids = tuple(value.sample_id for value in ordered)
    indices = tuple(value.session_index for value in ordered)
    if len(sample_ids) != len(set(sample_ids)) or len(indices) != len(set(indices)):
        raise ValueError("walk-forward sample IDs and session indices must be unique")
    if indices != tuple(range(len(ordered))):
        raise ValueError("walk-forward session indices must be contiguous and start at zero")
    if len({value.feature_version_id for value in ordered}) > 1:
        raise ValueError("walk-forward samples must freeze one feature version")
    if len({value.label_version_id for value in ordered}) > 1:
        raise ValueError("walk-forward samples must freeze one label version")
    for value in ordered:
        if value.label_end_session_index - value.session_index != spec.horizon_sessions:
            raise ValueError("sample label horizon does not match horizon_sessions")
        if mode is DataMode.STRICT_HISTORICAL and (
            value.feature_trust_state is not DataTrustState.PIT_VERIFIED
            or value.label_trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise PermissionError("strict_historical split requires pit_verified samples")
        if value.data_mode is not mode:
            raise PermissionError("current samples cannot be relabelled as historical results")
    return ordered


def purged_embargoed_walk_forward(
    samples: Sequence[WalkForwardSample],
    *,
    spec: WalkForwardSpec,
    data_mode: DataMode,
) -> WalkForwardResult:
    """Build deterministic expanding walk-forward folds with explicit exclusions."""

    if not isinstance(spec, WalkForwardSpec):
        raise TypeError("spec must be WalkForwardSpec")
    rows = tuple(samples)
    if any(not isinstance(value, WalkForwardSample) for value in rows):
        raise TypeError("samples must contain WalkForwardSample values")
    mode = DataMode(data_mode)
    ordered = _validate_walk_forward_context(rows, mode, spec)
    feature_versions = tuple(sorted({value.feature_version_id for value in ordered}))
    label_versions = tuple(sorted({value.label_version_id for value in ordered}))
    missing = tuple(sorted(value.sample_id for value in ordered if not value.available))
    reason: str | None = None
    folds: list[WalkForwardFold] = []
    if missing:
        reason = "missing feature or label samples make the walk-forward plan unavailable"
    else:
        test_start = spec.initial_training_sessions
        while test_start + spec.test_sessions <= len(ordered):
            test_end = test_start + spec.test_sessions - 1
            cutoff = test_start - spec.purge_sessions
            candidates = tuple(value for value in ordered if value.session_index < test_start)
            training = tuple(
                value for value in candidates if value.label_end_session_index < cutoff
            )
            purged = tuple(
                value for value in candidates if value.label_end_session_index >= cutoff
            )
            if len(training) < spec.minimum_training_samples:
                reason = (
                    f"post-purge training sample_size={len(training)} is below "
                    f"minimum_training_samples={spec.minimum_training_samples}"
                )
                folds = []
                break
            test = tuple(
                value
                for value in ordered
                if test_start <= value.session_index <= test_end
            )
            embargo_start = test_end + 1 if spec.embargo_sessions else None
            embargo_end = test_end + spec.embargo_sessions if spec.embargo_sessions else None
            embargoed = tuple(
                value
                for value in ordered
                if embargo_start is not None
                and embargo_end is not None
                and embargo_start <= value.session_index <= embargo_end
            )
            folds.append(
                WalkForwardFold(
                    fold_index=len(folds) + 1,
                    train_candidate_end_session_index=test_start - 1,
                    purge_cutoff_session_index=cutoff,
                    test_start_session_index=test_start,
                    test_end_session_index=test_end,
                    embargo_start_session_index=embargo_start,
                    embargo_end_session_index=embargo_end,
                    training_sample_ids=tuple(value.sample_id for value in training),
                    purged_sample_ids=tuple(value.sample_id for value in purged),
                    test_sample_ids=tuple(value.sample_id for value in test),
                    embargoed_sample_ids=tuple(value.sample_id for value in embargoed),
                )
            )
            test_start += spec.step_sessions
        if not folds and reason is None:
            reason = "sample range does not contain a complete walk-forward test fold"
    return WalkForwardResult(
        status=(
            ValidationCalculationStatus.QUANTIFIED
            if folds
            else ValidationCalculationStatus.UNAVAILABLE
        ),
        folds=tuple(folds),
        split_version=spec.split_version,
        horizon_sessions=spec.horizon_sessions,
        purge_sessions=spec.purge_sessions,
        embargo_sessions=spec.embargo_sessions,
        feature_version_ids=feature_versions,
        label_version_ids=label_versions,
        missing_sample_ids=missing,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=ValidationScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "BHDecision",
    "BHFamilyResult",
    "BHFamilySpec",
    "HypothesisPValue",
    "ValidationCalculationStatus",
    "ValidationScientificStatus",
    "WalkForwardFold",
    "WalkForwardResult",
    "WalkForwardSample",
    "WalkForwardSpec",
    "benjamini_hochberg",
    "purged_embargoed_walk_forward",
]
