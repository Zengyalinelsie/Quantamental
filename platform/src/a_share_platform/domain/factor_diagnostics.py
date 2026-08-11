"""Pure P4 factor diagnostics: quantiles, decay, turnover, and coverage.

These deterministic statistics are diagnostics, not evidence that a factor is
scientifically valid. Missing observations remain explicit and are never
converted into numeric zeroes.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from .factor_statistics import (
    CrossSectionObservation,
    StatisticsScientificStatus,
    StatisticStatus,
)
from .pit import DataTrustState
from .run_context import DataMode


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _number(value: float | None, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number or None")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _warnings(mode: DataMode) -> tuple[str, ...]:
    if mode is DataMode.CURRENT_RESEARCH:
        return ("current_research diagnostic is not a historical factor result",)
    return ()


def _evidence_gate(
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
    decision_time: datetime,
    available_at: datetime,
    label: str,
) -> tuple[DataMode, DataTrustState]:
    mode = DataMode(data_mode)
    trust = DataTrustState(trust_state)
    if trust is DataTrustState.RAW:
        raise ValueError(f"raw observations cannot enter {label}")
    if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
        raise PermissionError(f"strict_historical {label} requires pit_verified inputs")
    decision = _aware(decision_time, "decision_time")
    available = _aware(available_at, "available_at")
    if available > decision:
        raise ValueError("available_at cannot exceed decision_time")
    return mode, trust


def _require_requested_mode(
    actual_mode: DataMode,
    trust_state: DataTrustState,
    requested_mode: DataMode,
    label: str,
) -> None:
    if actual_mode is not requested_mode:
        raise PermissionError(
            f"current {label} observations cannot be relabelled as historical results"
        )
    if (
        requested_mode is DataMode.STRICT_HISTORICAL
        and trust_state is not DataTrustState.PIT_VERIFIED
    ):
        raise PermissionError(f"strict_historical {label} requires pit_verified inputs")


@dataclass(frozen=True)
class QuantilePortfolioSpec:
    quantile_count: int
    minimum_sample_size: int
    formula_version: str
    tie_break_version: str

    def __post_init__(self) -> None:
        if type(self.quantile_count) is not int or self.quantile_count < 2:
            raise ValueError("quantile_count must be an integer >= 2")
        if (
            type(self.minimum_sample_size) is not int
            or self.minimum_sample_size < self.quantile_count
        ):
            raise ValueError("minimum_sample_size must be >= quantile_count")
        _text(self.formula_version, "formula_version")
        _text(self.tie_break_version, "tie_break_version")


@dataclass(frozen=True)
class QuantileReturn:
    quantile: int
    mean_return: float
    member_count: int


@dataclass(frozen=True)
class QuantilePortfolioResult:
    status: StatisticStatus
    quantiles: tuple[QuantileReturn, ...]
    monotonic: bool | None
    monotonicity_ratio: float | None
    top_minus_bottom: float | None
    sample_size: int
    missing_count: int
    quantile_count: int
    minimum_sample_size: int
    formula_version: str
    tie_break_version: str
    input_score_version_ids: tuple[str, ...]
    input_label_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


def quantile_portfolios(
    observations: Sequence[CrossSectionObservation],
    *,
    spec: QuantilePortfolioSpec,
    data_mode: DataMode,
) -> QuantilePortfolioResult:
    if not isinstance(spec, QuantilePortfolioSpec):
        raise TypeError("spec must be QuantilePortfolioSpec")
    rows = tuple(observations)
    if any(not isinstance(value, CrossSectionObservation) for value in rows):
        raise TypeError("observations must contain CrossSectionObservation values")
    mode = DataMode(data_mode)
    entity_ids = tuple(value.entity_id for value in rows)
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError("cross-section entity_id values must be unique")
    if len({value.decision_time for value in rows}) > 1:
        raise ValueError("cross-section observations must share one decision_time")
    if len({value.label_outcome_at for value in rows}) > 1:
        raise ValueError("cross-section observations must share one label outcome time")
    for value in rows:
        _require_requested_mode(
            value.data_mode,
            value.score_trust_state,
            mode,
            "quantile",
        )
        if (
            mode is DataMode.STRICT_HISTORICAL
            and value.label_trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise PermissionError("strict_historical quantiles require pit_verified labels")
    score_versions = tuple(sorted({value.score_version_id for value in rows}))
    label_versions = tuple(sorted({value.label_version_id for value in rows}))
    if len(score_versions) > 1 or len(label_versions) > 1:
        raise ValueError("quantiles must freeze one score and one label version")
    complete = tuple(
        value for value in rows if value.score is not None and value.forward_return is not None
    )
    missing_count = len(rows) - len(complete)
    if len(complete) < spec.minimum_sample_size:
        return QuantilePortfolioResult(
            status=StatisticStatus.UNAVAILABLE,
            quantiles=(),
            monotonic=None,
            monotonicity_ratio=None,
            top_minus_bottom=None,
            sample_size=len(complete),
            missing_count=missing_count,
            quantile_count=spec.quantile_count,
            minimum_sample_size=spec.minimum_sample_size,
            formula_version=spec.formula_version,
            tie_break_version=spec.tie_break_version,
            input_score_version_ids=score_versions,
            input_label_version_ids=label_versions,
            data_mode=mode,
            historical_eligible=mode is DataMode.STRICT_HISTORICAL,
            unavailable_reason=(
                f"sample_size={len(complete)} is below "
                f"minimum_sample_size={spec.minimum_sample_size}"
            ),
            warnings=_warnings(mode),
            scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
        )
    ordered = tuple(
        sorted(
            complete,
            key=lambda value: (
                value.score if value.score is not None else 0.0,
                value.entity_id,
            ),
        )
    )
    buckets: list[list[float]] = [[] for _ in range(spec.quantile_count)]
    for index, value in enumerate(ordered):
        bucket = min(spec.quantile_count - 1, index * spec.quantile_count // len(ordered))
        assert value.forward_return is not None
        buckets[bucket].append(value.forward_return)
    quantiles = tuple(
        QuantileReturn(
            quantile=index + 1,
            mean_return=math.fsum(values) / len(values),
            member_count=len(values),
        )
        for index, values in enumerate(buckets)
    )
    adjacent = tuple(right.mean_return - left.mean_return for left, right in pairwise(quantiles))
    monotonic_count = sum(value >= 0 for value in adjacent)
    return QuantilePortfolioResult(
        status=StatisticStatus.QUANTIFIED,
        quantiles=quantiles,
        monotonic=monotonic_count == len(adjacent),
        monotonicity_ratio=monotonic_count / len(adjacent),
        top_minus_bottom=quantiles[-1].mean_return - quantiles[0].mean_return,
        sample_size=len(complete),
        missing_count=missing_count,
        quantile_count=spec.quantile_count,
        minimum_sample_size=spec.minimum_sample_size,
        formula_version=spec.formula_version,
        tie_break_version=spec.tie_break_version,
        input_score_version_ids=score_versions,
        input_label_version_ids=label_versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=None,
        warnings=_warnings(mode),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


@dataclass(frozen=True)
class DecayObservation:
    horizon_sessions: int
    correlation: float | None
    statistic_version_id: str
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    available_at: datetime
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.horizon_sessions) is not int or self.horizon_sessions <= 0:
            raise ValueError("horizon_sessions must be a positive integer")
        value = _number(self.correlation, "correlation")
        if value is not None and not -1 <= value <= 1:
            raise ValueError("correlation must be between -1 and 1")
        object.__setattr__(self, "correlation", value)
        _text(self.statistic_version_id, "statistic_version_id")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            available_at=self.available_at,
            label="decay",
        )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if value is None:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete decay observation cannot carry missing_reason")


@dataclass(frozen=True)
class DecaySpec:
    minimum_horizons: int
    formula_version: str
    half_life_fraction: float

    def __post_init__(self) -> None:
        if type(self.minimum_horizons) is not int or self.minimum_horizons < 2:
            raise ValueError("minimum_horizons must be an integer >= 2")
        _text(self.formula_version, "formula_version")
        fraction = _number(self.half_life_fraction, "half_life_fraction")
        assert fraction is not None
        if not 0 < fraction <= 1:
            raise ValueError("half_life_fraction must be in (0, 1]")
        object.__setattr__(self, "half_life_fraction", fraction)


@dataclass(frozen=True)
class DecayPoint:
    horizon_sessions: int
    correlation: float
    normalized_strength: float


@dataclass(frozen=True)
class DecayResult:
    status: StatisticStatus
    points: tuple[DecayPoint, ...]
    half_life_sessions: int | None
    sample_size: int
    missing_count: int
    minimum_horizons: int
    half_life_fraction: float
    formula_version: str
    input_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


def factor_decay(
    observations: Sequence[DecayObservation],
    *,
    spec: DecaySpec,
    data_mode: DataMode,
) -> DecayResult:
    if not isinstance(spec, DecaySpec):
        raise TypeError("spec must be DecaySpec")
    rows = tuple(observations)
    if any(not isinstance(value, DecayObservation) for value in rows):
        raise TypeError("observations must contain DecayObservation values")
    mode = DataMode(data_mode)
    horizons = tuple(value.horizon_sessions for value in rows)
    if len(horizons) != len(set(horizons)):
        raise ValueError("decay horizons must be unique")
    versions = tuple(sorted({value.statistic_version_id for value in rows}))
    if len(versions) > 1:
        raise ValueError("decay observations must freeze one statistic version")
    if len({value.decision_time for value in rows}) > 1:
        raise ValueError("decay observations must share one decision_time")
    for value in rows:
        _require_requested_mode(value.data_mode, value.trust_state, mode, "decay")
    complete = tuple(
        sorted(
            (value for value in rows if value.correlation is not None),
            key=lambda value: value.horizon_sessions,
        )
    )
    missing_count = len(rows) - len(complete)
    reason: str | None = None
    if len(complete) < spec.minimum_horizons:
        reason = f"horizon_count={len(complete)} is below minimum_horizons={spec.minimum_horizons}"
    elif complete[0].correlation == 0:
        reason = "first-horizon correlation is zero, so normalized decay is unavailable"
    if reason is not None:
        return DecayResult(
            status=StatisticStatus.UNAVAILABLE,
            points=(),
            half_life_sessions=None,
            sample_size=len(complete),
            missing_count=missing_count,
            minimum_horizons=spec.minimum_horizons,
            half_life_fraction=spec.half_life_fraction,
            formula_version=spec.formula_version,
            input_version_ids=versions,
            data_mode=mode,
            historical_eligible=mode is DataMode.STRICT_HISTORICAL,
            unavailable_reason=reason,
            warnings=_warnings(mode),
            scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
        )
    baseline = abs(complete[0].correlation or 0.0)
    points = tuple(
        DecayPoint(
            horizon_sessions=value.horizon_sessions,
            correlation=value.correlation or 0.0,
            normalized_strength=abs(value.correlation or 0.0) / baseline,
        )
        for value in complete
    )
    half_life = next(
        (
            value.horizon_sessions
            for value in points
            if value.normalized_strength <= spec.half_life_fraction
        ),
        None,
    )
    warnings = list(_warnings(mode))
    if half_life is None:
        warnings.append("decay half-life was not observed in the supplied horizons")
    return DecayResult(
        status=StatisticStatus.QUANTIFIED,
        points=points,
        half_life_sessions=half_life,
        sample_size=len(complete),
        missing_count=missing_count,
        minimum_horizons=spec.minimum_horizons,
        half_life_fraction=spec.half_life_fraction,
        formula_version=spec.formula_version,
        input_version_ids=versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=None,
        warnings=tuple(warnings),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


@dataclass(frozen=True)
class TurnoverObservation:
    period_id: str
    entity_id: str
    weight: float | None
    portfolio_version_id: str
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    available_at: datetime
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("period_id", "entity_id", "portfolio_version_id"):
            _text(getattr(self, name), name)
        weight = _number(self.weight, "weight")
        if weight is not None and not 0 <= weight <= 1:
            raise ValueError("weight must be between 0 and 1")
        object.__setattr__(self, "weight", weight)
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            available_at=self.available_at,
            label="turnover",
        )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if weight is None:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete turnover observation cannot carry missing_reason")


@dataclass(frozen=True)
class TurnoverSpec:
    minimum_positions_per_period: int
    weight_sum_tolerance: float
    formula_version: str

    def __post_init__(self) -> None:
        if (
            type(self.minimum_positions_per_period) is not int
            or self.minimum_positions_per_period <= 0
        ):
            raise ValueError("minimum_positions_per_period must be positive")
        tolerance = _number(self.weight_sum_tolerance, "weight_sum_tolerance")
        assert tolerance is not None
        if not 0 <= tolerance < 1:
            raise ValueError("weight_sum_tolerance must be in [0, 1)")
        object.__setattr__(self, "weight_sum_tolerance", tolerance)
        _text(self.formula_version, "formula_version")


@dataclass(frozen=True)
class TurnoverResult:
    status: StatisticStatus
    value: float | None
    period_ids: tuple[str, ...]
    position_counts: tuple[int, ...]
    missing_count: int
    minimum_positions_per_period: int
    weight_sum_tolerance: float
    formula_version: str
    input_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


def portfolio_turnover(
    observations: Sequence[TurnoverObservation],
    *,
    spec: TurnoverSpec,
    data_mode: DataMode,
) -> TurnoverResult:
    if not isinstance(spec, TurnoverSpec):
        raise TypeError("spec must be TurnoverSpec")
    rows = tuple(observations)
    if any(not isinstance(value, TurnoverObservation) for value in rows):
        raise TypeError("observations must contain TurnoverObservation values")
    mode = DataMode(data_mode)
    period_ids = tuple(dict.fromkeys(value.period_id for value in rows))
    if len(period_ids) != 2:
        raise ValueError("turnover requires exactly two ordered periods")
    keys = tuple((value.period_id, value.entity_id) for value in rows)
    if len(keys) != len(set(keys)):
        raise ValueError("turnover period/entity observations must be unique")
    versions = tuple(sorted({value.portfolio_version_id for value in rows}))
    if len(versions) > 1:
        raise ValueError("turnover observations must freeze one portfolio version")
    for value in rows:
        _require_requested_mode(value.data_mode, value.trust_state, mode, "turnover")
    by_period = {
        period: tuple(value for value in rows if value.period_id == period) for period in period_ids
    }
    counts = tuple(len(by_period[period]) for period in period_ids)
    missing_count = sum(value.weight is None for value in rows)
    reason: str | None = None
    if any(count < spec.minimum_positions_per_period for count in counts):
        reason = "a turnover period is below minimum_positions_per_period"
    elif missing_count:
        reason = "turnover weights contain explicit missing values"
    else:
        weight_sums = tuple(
            math.fsum(value.weight for value in by_period[period] if value.weight is not None)
            for period in period_ids
        )
        if any(abs(value - 1.0) > spec.weight_sum_tolerance for value in weight_sums):
            reason = "turnover portfolio weights do not sum to one within tolerance"
    if reason is None:
        weights = {
            period: {
                value.entity_id: value.weight
                for value in by_period[period]
                if value.weight is not None
            }
            for period in period_ids
        }
        entities = set(weights[period_ids[0]]) | set(weights[period_ids[1]])
        result = 0.5 * math.fsum(
            abs(weights[period_ids[1]].get(entity, 0.0) - weights[period_ids[0]].get(entity, 0.0))
            for entity in entities
        )
    else:
        result = None
    return TurnoverResult(
        status=StatisticStatus.QUANTIFIED if result is not None else StatisticStatus.UNAVAILABLE,
        value=result,
        period_ids=period_ids,
        position_counts=counts,
        missing_count=missing_count,
        minimum_positions_per_period=spec.minimum_positions_per_period,
        weight_sum_tolerance=spec.weight_sum_tolerance,
        formula_version=spec.formula_version,
        input_version_ids=versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


@dataclass(frozen=True)
class CoverageObservation:
    entity_id: str
    eligible: bool
    score: float | None
    universe_version_id: str
    score_version_id: str
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    available_at: datetime
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("entity_id", "universe_version_id", "score_version_id"):
            _text(getattr(self, name), name)
        if type(self.eligible) is not bool:
            raise TypeError("eligible must be a boolean")
        score = _number(self.score, "score")
        object.__setattr__(self, "score", score)
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            available_at=self.available_at,
            label="coverage",
        )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if score is None:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete coverage observation cannot carry missing_reason")


@dataclass(frozen=True)
class CoverageSpec:
    minimum_eligible_count: int
    minimum_coverage_ratio: float
    formula_version: str

    def __post_init__(self) -> None:
        if type(self.minimum_eligible_count) is not int or self.minimum_eligible_count <= 0:
            raise ValueError("minimum_eligible_count must be positive")
        ratio = _number(self.minimum_coverage_ratio, "minimum_coverage_ratio")
        assert ratio is not None
        if not 0 <= ratio <= 1:
            raise ValueError("minimum_coverage_ratio must be between 0 and 1")
        object.__setattr__(self, "minimum_coverage_ratio", ratio)
        _text(self.formula_version, "formula_version")


@dataclass(frozen=True)
class CoverageResult:
    status: StatisticStatus
    value: float | None
    eligible_count: int
    quantified_count: int
    missing_count: int
    meets_minimum: bool
    minimum_eligible_count: int
    minimum_coverage_ratio: float
    formula_version: str
    universe_version_ids: tuple[str, ...]
    score_version_ids: tuple[str, ...]
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus


def factor_coverage(
    observations: Sequence[CoverageObservation],
    *,
    spec: CoverageSpec,
    data_mode: DataMode,
) -> CoverageResult:
    if not isinstance(spec, CoverageSpec):
        raise TypeError("spec must be CoverageSpec")
    rows = tuple(observations)
    if any(not isinstance(value, CoverageObservation) for value in rows):
        raise TypeError("observations must contain CoverageObservation values")
    mode = DataMode(data_mode)
    entity_ids = tuple(value.entity_id for value in rows)
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError("coverage entity_id values must be unique")
    universe_versions = tuple(sorted({value.universe_version_id for value in rows}))
    score_versions = tuple(sorted({value.score_version_id for value in rows}))
    if len(universe_versions) > 1 or len(score_versions) > 1:
        raise ValueError("coverage must freeze one universe and one score version")
    if len({value.decision_time for value in rows}) > 1:
        raise ValueError("coverage observations must share one decision_time")
    for value in rows:
        _require_requested_mode(value.data_mode, value.trust_state, mode, "coverage")
    eligible = tuple(value for value in rows if value.eligible)
    quantified = tuple(value for value in eligible if value.score is not None)
    missing_count = len(eligible) - len(quantified)
    if len(eligible) < spec.minimum_eligible_count:
        coverage_value = None
        reason = (
            f"eligible_count={len(eligible)} is below "
            f"minimum_eligible_count={spec.minimum_eligible_count}"
        )
        meets_minimum = False
        status = StatisticStatus.UNAVAILABLE
    else:
        coverage_value = len(quantified) / len(eligible)
        reason = None
        meets_minimum = coverage_value >= spec.minimum_coverage_ratio
        status = StatisticStatus.QUANTIFIED
    return CoverageResult(
        status=status,
        value=coverage_value,
        eligible_count=len(eligible),
        quantified_count=len(quantified),
        missing_count=missing_count,
        meets_minimum=meets_minimum,
        minimum_eligible_count=spec.minimum_eligible_count,
        minimum_coverage_ratio=spec.minimum_coverage_ratio,
        formula_version=spec.formula_version,
        universe_version_ids=universe_versions,
        score_version_ids=score_versions,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "CoverageObservation",
    "CoverageResult",
    "CoverageSpec",
    "DecayObservation",
    "DecayPoint",
    "DecayResult",
    "DecaySpec",
    "QuantilePortfolioResult",
    "QuantilePortfolioSpec",
    "QuantileReturn",
    "TurnoverObservation",
    "TurnoverResult",
    "TurnoverSpec",
    "factor_coverage",
    "factor_decay",
    "portfolio_turnover",
    "quantile_portfolios",
]
