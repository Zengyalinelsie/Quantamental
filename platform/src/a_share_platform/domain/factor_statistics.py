"""Dependency-free first slice of the P4 factor statistical engine.

The functions are deterministic and provider-neutral.  They report statistical
estimates only; they do not establish factor validity or lifecycle promotion.
Current-research observations may be inspected, but are never labelled as
historical evidence.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .pit import DataTrustState
from .run_context import DataMode


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _optional_number(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number or None")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _present_number(value: float | None) -> float:
    if value is None:
        raise AssertionError("complete observation unexpectedly contains a missing value")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class StatisticStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


class CorrelationKind(str, Enum):
    PEARSON = "pearson"
    SPEARMAN = "spearman"


class StatisticsScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class CrossSectionObservation:
    entity_id: str
    score: float | None
    forward_return: float | None
    score_version_id: str
    label_version_id: str
    data_mode: DataMode
    score_trust_state: DataTrustState
    label_trust_state: DataTrustState
    decision_time: datetime
    score_available_at: datetime
    label_outcome_at: datetime
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("entity_id", "score_version_id", "label_version_id"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "score", _optional_number(self.score, "score"))
        object.__setattr__(
            self,
            "forward_return",
            _optional_number(self.forward_return, "forward_return"),
        )
        mode = DataMode(self.data_mode)
        score_trust = DataTrustState(self.score_trust_state)
        label_trust = DataTrustState(self.label_trust_state)
        if DataTrustState.RAW in {score_trust, label_trust}:
            raise ValueError("raw observations cannot enter factor statistics")
        if mode is DataMode.STRICT_HISTORICAL and {
            score_trust,
            label_trust,
        } != {DataTrustState.PIT_VERIFIED}:
            raise PermissionError("strict_historical IC observations must be pit_verified")
        decision_time = _aware(self.decision_time, "decision_time")
        score_available_at = _aware(self.score_available_at, "score_available_at")
        label_outcome_at = _aware(self.label_outcome_at, "label_outcome_at")
        if score_available_at > decision_time:
            raise ValueError("score available_at cannot exceed decision_time")
        if label_outcome_at <= decision_time:
            raise ValueError("label outcome must follow decision_time")
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "score_trust_state", score_trust)
        object.__setattr__(self, "label_trust_state", label_trust)
        missing = self.score is None or self.forward_return is None
        if missing:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete IC observation cannot carry missing_reason")


@dataclass(frozen=True)
class TimeSeriesObservation:
    period_id: str
    value: float | None
    statistic_version_id: str
    data_mode: DataMode
    trust_state: DataTrustState
    availability_enforced: bool
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.period_id, "period_id")
        _text(self.statistic_version_id, "statistic_version_id")
        object.__setattr__(self, "value", _optional_number(self.value, "value"))
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw observations cannot enter factor statistics")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical statistic observations must be pit_verified")
        if type(self.availability_enforced) is not bool:
            raise TypeError("availability_enforced must be a boolean")
        if mode is DataMode.STRICT_HISTORICAL and not self.availability_enforced:
            raise PermissionError(
                "strict_historical statistic requires source availability enforcement"
            )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if self.value is None:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete time-series observation cannot carry missing_reason")


@dataclass(frozen=True)
class CorrelationSpec:
    kind: CorrelationKind
    minimum_sample_size: int
    formula_version: str
    rank_version: str | None

    def __post_init__(self) -> None:
        kind = CorrelationKind(self.kind)
        if type(self.minimum_sample_size) is not int or self.minimum_sample_size < 3:
            raise ValueError("minimum_sample_size must be an integer >= 3")
        _text(self.formula_version, "formula_version")
        if kind is CorrelationKind.SPEARMAN:
            _text(self.rank_version or "", "rank_version")
        elif self.rank_version is not None:
            raise ValueError("Pearson correlation must not carry rank_version")
        object.__setattr__(self, "kind", kind)


@dataclass(frozen=True)
class HACNeweyWestSpec:
    max_lag: int
    minimum_sample_size: int
    formula_version: str

    def __post_init__(self) -> None:
        if type(self.max_lag) is not int or self.max_lag < 0:
            raise ValueError("max_lag must be a non-negative integer")
        if (
            type(self.minimum_sample_size) is not int
            or self.minimum_sample_size <= self.max_lag + 1
        ):
            raise ValueError("minimum_sample_size must exceed max_lag + 1")
        _text(self.formula_version, "formula_version")


@dataclass(frozen=True)
class BlockBootstrapSpec:
    block_size: int
    resamples: int
    confidence_level: float
    seed: int
    minimum_sample_size: int
    formula_version: str

    def __post_init__(self) -> None:
        if type(self.block_size) is not int or self.block_size <= 0:
            raise ValueError("block_size must be a positive integer")
        if type(self.resamples) is not int or self.resamples < 100:
            raise ValueError("resamples must be an integer >= 100")
        confidence = _optional_number(self.confidence_level, "confidence_level")
        assert confidence is not None
        if not 0 < confidence < 1:
            raise ValueError("confidence_level must be between zero and one")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("seed must be a non-negative integer")
        if type(self.minimum_sample_size) is not int or self.minimum_sample_size < 2:
            raise ValueError("minimum_sample_size must be an integer >= 2")
        _text(self.formula_version, "formula_version")
        object.__setattr__(self, "confidence_level", confidence)


@dataclass(frozen=True)
class CorrelationResult:
    status: StatisticStatus
    kind: CorrelationKind
    value: float | None
    sample_size: int
    missing_count: int
    minimum_sample_size: int
    formula_version: str
    rank_version: str | None
    input_score_version_ids: tuple[str, ...]
    input_label_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


@dataclass(frozen=True)
class HACNeweyWestResult:
    status: StatisticStatus
    mean: float | None
    long_run_variance: float | None
    standard_error: float | None
    t_statistic: float | None
    sample_size: int
    missing_count: int
    max_lag: int
    minimum_sample_size: int
    formula_version: str
    input_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


@dataclass(frozen=True)
class BlockBootstrapResult:
    status: StatisticStatus
    sample_mean: float | None
    lower_bound: float | None
    upper_bound: float | None
    sample_size: int
    missing_count: int
    block_size: int
    resamples: int
    confidence_level: float
    seed: int
    minimum_sample_size: int
    formula_version: str
    input_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


def _warnings(data_mode: DataMode) -> tuple[str, ...]:
    if data_mode is DataMode.CURRENT_RESEARCH:
        return ("current_research statistic is diagnostic and not a historical result",)
    return ()


def _validate_cross_context(
    observations: tuple[CrossSectionObservation, ...],
    data_mode: DataMode,
) -> None:
    entity_ids = tuple(value.entity_id for value in observations)
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError("cross-section entity_id values must be unique")
    if len({value.decision_time for value in observations}) > 1:
        raise ValueError("cross-section observations must share one decision_time")
    if len({value.label_outcome_at for value in observations}) > 1:
        raise ValueError("cross-section observations must share one label outcome time")
    for value in observations:
        if data_mode is DataMode.STRICT_HISTORICAL and (
            value.score_trust_state is not DataTrustState.PIT_VERIFIED
            or value.label_trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise PermissionError("strict_historical IC requires pit_verified inputs")
        if value.data_mode is not data_mode:
            raise PermissionError("current scores cannot be relabelled as historical results")


def _validate_time_context(
    observations: tuple[TimeSeriesObservation, ...],
    data_mode: DataMode,
) -> None:
    period_ids = tuple(value.period_id for value in observations)
    if len(period_ids) != len(set(period_ids)):
        raise ValueError("time-series period_id values must be unique")
    versions = {value.statistic_version_id for value in observations}
    if len(versions) > 1:
        raise ValueError("time-series observations must freeze one statistic version")
    for value in observations:
        if data_mode is DataMode.STRICT_HISTORICAL and value.trust_state is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical statistic requires pit_verified inputs")
        if value.data_mode is not data_mode:
            raise PermissionError("current statistics cannot be relabelled as historical results")


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    left_mean = math.fsum(left) / len(left)
    right_mean = math.fsum(right) / len(right)
    left_centered = tuple(value - left_mean for value in left)
    right_centered = tuple(value - right_mean for value in right)
    denominator = math.sqrt(
        math.fsum(value * value for value in left_centered)
        * math.fsum(value * value for value in right_centered)
    )
    if denominator == 0:
        return None
    value = math.fsum(
        left_value * right_value
        for left_value, right_value in zip(left_centered, right_centered)
    ) / denominator
    return max(-1.0, min(1.0, value))


def _average_ranks(values: Sequence[float]) -> tuple[float, ...]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = ((start + 1) + end) / 2
        for position in range(start, end):
            ranks[indexed[position][0]] = average_rank
        start = end
    return tuple(ranks)


def information_coefficient(
    observations: Sequence[CrossSectionObservation],
    *,
    spec: CorrelationSpec,
    data_mode: DataMode,
) -> CorrelationResult:
    if not isinstance(spec, CorrelationSpec):
        raise TypeError("spec must be CorrelationSpec")
    rows = tuple(observations)
    if any(not isinstance(value, CrossSectionObservation) for value in rows):
        raise TypeError("observations must contain CrossSectionObservation values")
    mode = DataMode(data_mode)
    _validate_cross_context(rows, mode)
    score_versions = tuple(sorted({value.score_version_id for value in rows}))
    label_versions = tuple(sorted({value.label_version_id for value in rows}))
    if len(score_versions) > 1 or len(label_versions) > 1:
        raise ValueError("IC observations must freeze one score and one label version")
    complete = tuple(
        value for value in rows if value.score is not None and value.forward_return is not None
    )
    missing_count = len(rows) - len(complete)
    reason: str | None = None
    result: float | None = None
    if len(complete) < spec.minimum_sample_size:
        reason = (
            f"sample_size={len(complete)} is below "
            f"minimum_sample_size={spec.minimum_sample_size}"
        )
    else:
        numeric_scores = tuple(_present_number(value.score) for value in complete)
        numeric_returns = tuple(_present_number(value.forward_return) for value in complete)
        if spec.kind is CorrelationKind.SPEARMAN:
            numeric_scores = _average_ranks(numeric_scores)
            numeric_returns = _average_ranks(numeric_returns)
        result = _pearson(numeric_scores, numeric_returns)
        if result is None:
            reason = "correlation is unavailable for a constant score or return series"
    return CorrelationResult(
        status=(StatisticStatus.QUANTIFIED if result is not None else StatisticStatus.UNAVAILABLE),
        kind=spec.kind,
        value=result,
        sample_size=len(complete),
        missing_count=missing_count,
        minimum_sample_size=spec.minimum_sample_size,
        formula_version=spec.formula_version,
        rank_version=spec.rank_version,
        input_score_version_ids=score_versions,
        input_label_version_ids=label_versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


def newey_west_mean_test(
    observations: Sequence[TimeSeriesObservation],
    *,
    spec: HACNeweyWestSpec,
    data_mode: DataMode,
) -> HACNeweyWestResult:
    if not isinstance(spec, HACNeweyWestSpec):
        raise TypeError("spec must be HACNeweyWestSpec")
    rows = tuple(observations)
    if any(not isinstance(value, TimeSeriesObservation) for value in rows):
        raise TypeError("observations must contain TimeSeriesObservation values")
    mode = DataMode(data_mode)
    _validate_time_context(rows, mode)
    missing_count = sum(value.value is None for value in rows)
    versions = tuple(sorted({value.statistic_version_id for value in rows}))
    reason: str | None = None
    mean = long_run_variance = standard_error = t_statistic = None
    if missing_count:
        reason = "missing time-series observations cannot be compressed across HAC lags"
    elif len(rows) < spec.minimum_sample_size:
        reason = (
            f"sample_size={len(rows)} is below "
            f"minimum_sample_size={spec.minimum_sample_size}"
        )
    else:
        values = tuple(float(value.value) for value in rows if value.value is not None)
        mean = math.fsum(values) / len(values)
        centered = tuple(value - mean for value in values)
        sample_size = len(values)
        gamma_zero = math.fsum(value * value for value in centered) / sample_size
        long_run_variance = gamma_zero
        for lag in range(1, spec.max_lag + 1):
            covariance = math.fsum(
                centered[index] * centered[index - lag]
                for index in range(lag, sample_size)
            ) / sample_size
            bartlett_weight = 1 - lag / (spec.max_lag + 1)
            long_run_variance += 2 * bartlett_weight * covariance
        if long_run_variance <= 0:
            reason = "Newey-West long-run variance is non-positive"
            mean = long_run_variance = None
        else:
            standard_error = math.sqrt(long_run_variance / sample_size)
            t_statistic = mean / standard_error
    return HACNeweyWestResult(
        status=(
            StatisticStatus.QUANTIFIED
            if t_statistic is not None
            else StatisticStatus.UNAVAILABLE
        ),
        mean=mean,
        long_run_variance=long_run_variance,
        standard_error=standard_error,
        t_statistic=t_statistic,
        sample_size=len(rows) - missing_count,
        missing_count=missing_count,
        max_lag=spec.max_lag,
        minimum_sample_size=spec.minimum_sample_size,
        formula_version=spec.formula_version,
        input_version_ids=versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


def _linear_quantile(sorted_values: Sequence[float], probability: float) -> float:
    position = (len(sorted_values) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return sorted_values[lower_index]
    weight = position - lower_index
    return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight


def block_bootstrap_mean_ci(
    observations: Sequence[TimeSeriesObservation],
    *,
    spec: BlockBootstrapSpec,
    data_mode: DataMode,
) -> BlockBootstrapResult:
    if not isinstance(spec, BlockBootstrapSpec):
        raise TypeError("spec must be BlockBootstrapSpec")
    rows = tuple(observations)
    if any(not isinstance(value, TimeSeriesObservation) for value in rows):
        raise TypeError("observations must contain TimeSeriesObservation values")
    mode = DataMode(data_mode)
    _validate_time_context(rows, mode)
    missing_count = sum(value.value is None for value in rows)
    versions = tuple(sorted({value.statistic_version_id for value in rows}))
    reason: str | None = None
    sample_mean = lower_bound = upper_bound = None
    if missing_count:
        reason = "missing time-series observations cannot be compressed into bootstrap blocks"
    elif len(rows) < spec.minimum_sample_size:
        reason = (
            f"sample_size={len(rows)} is below "
            f"minimum_sample_size={spec.minimum_sample_size}"
        )
    elif spec.block_size > len(rows):
        reason = f"block_size={spec.block_size} exceeds sample_size={len(rows)}"
    else:
        values = tuple(float(value.value) for value in rows if value.value is not None)
        sample_size = len(values)
        sample_mean = math.fsum(values) / sample_size
        generator = random.Random(spec.seed)
        bootstrap_means: list[float] = []
        for _ in range(spec.resamples):
            resampled: list[float] = []
            while len(resampled) < sample_size:
                start = generator.randrange(sample_size)
                resampled.extend(
                    values[(start + offset) % sample_size]
                    for offset in range(spec.block_size)
                )
            bootstrap_means.append(math.fsum(resampled[:sample_size]) / sample_size)
        ordered = tuple(sorted(bootstrap_means))
        tail = (1 - spec.confidence_level) / 2
        lower_bound = _linear_quantile(ordered, tail)
        upper_bound = _linear_quantile(ordered, 1 - tail)
    return BlockBootstrapResult(
        status=(
            StatisticStatus.QUANTIFIED
            if lower_bound is not None and upper_bound is not None
            else StatisticStatus.UNAVAILABLE
        ),
        sample_mean=sample_mean,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
        sample_size=len(rows) - missing_count,
        missing_count=missing_count,
        block_size=spec.block_size,
        resamples=spec.resamples,
        confidence_level=spec.confidence_level,
        seed=spec.seed,
        minimum_sample_size=spec.minimum_sample_size,
        formula_version=spec.formula_version,
        input_version_ids=versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "BlockBootstrapResult",
    "BlockBootstrapSpec",
    "CorrelationKind",
    "CorrelationResult",
    "CorrelationSpec",
    "CrossSectionObservation",
    "HACNeweyWestResult",
    "HACNeweyWestSpec",
    "StatisticStatus",
    "StatisticsScientificStatus",
    "TimeSeriesObservation",
    "block_bootstrap_mean_ci",
    "information_coefficient",
    "newey_west_mean_test",
]
