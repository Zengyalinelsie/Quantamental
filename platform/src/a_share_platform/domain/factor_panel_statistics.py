"""Panel and slice statistics for the P4 factor-validation baseline.

The module is dependency-free and provider-neutral.  Its outputs are
statistical estimates with explicit provenance and availability semantics;
they are not evidence that a factor is scientifically valid.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from .factor_statistics import StatisticsScientificStatus, StatisticStatus
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


def _present(value: float | None) -> float:
    if value is None:
        raise AssertionError("complete observation unexpectedly contains a missing value")
    return value


def _named_optional_numbers(
    values: Sequence[tuple[str, float | None]],
    field_name: str,
) -> tuple[tuple[str, float | None], ...]:
    result = tuple(values)
    names: list[str] = []
    normalized: list[tuple[str, float | None]] = []
    for name, value in result:
        names.append(_text(name, f"{field_name} name"))
        normalized.append((name, _number(value, f"{field_name}[{name}]")))
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return tuple(normalized)


def _named_versions(
    values: Sequence[tuple[str, str]],
    field_name: str,
) -> tuple[tuple[str, str], ...]:
    result = tuple(values)
    names: list[str] = []
    normalized: list[tuple[str, str]] = []
    for name, version in result:
        names.append(_text(name, f"{field_name} name"))
        normalized.append((name, _text(version, f"{field_name}[{name}]")))
    if not result:
        raise ValueError(f"{field_name} must not be empty")
    if len(names) != len(set(names)):
        raise ValueError(f"{field_name} names must be unique")
    return tuple(normalized)


def _validate_statistical_observation(
    *,
    data_mode: DataMode,
    factor_trust_state: DataTrustState,
    label_trust_state: DataTrustState,
    decision_time: datetime,
    factor_available_at: datetime,
    label_outcome_at: datetime,
) -> tuple[DataMode, DataTrustState, DataTrustState]:
    mode = DataMode(data_mode)
    factor_trust = DataTrustState(factor_trust_state)
    label_trust = DataTrustState(label_trust_state)
    if DataTrustState.RAW in {factor_trust, label_trust}:
        raise ValueError("raw observations cannot enter panel statistics")
    if mode is DataMode.STRICT_HISTORICAL and (
        factor_trust is not DataTrustState.PIT_VERIFIED
        or label_trust is not DataTrustState.PIT_VERIFIED
    ):
        raise PermissionError("strict_historical observations must be pit_verified")
    decision = _aware(decision_time, "decision_time")
    available = _aware(factor_available_at, "factor_available_at")
    outcome = _aware(label_outcome_at, "label_outcome_at")
    if available > decision:
        raise ValueError("factor available_at cannot exceed decision_time")
    if outcome <= decision:
        raise ValueError("label outcome must follow decision_time")
    return mode, factor_trust, label_trust


@dataclass(frozen=True)
class FamaMacBethObservation:
    period_id: str
    entity_id: str
    forward_return: float | None
    factor_values: tuple[tuple[str, float | None], ...]
    factor_version_ids: tuple[tuple[str, str], ...]
    label_version_id: str
    data_mode: DataMode
    factor_trust_state: DataTrustState
    label_trust_state: DataTrustState
    decision_time: datetime
    factor_available_at: datetime
    label_outcome_at: datetime
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        _text(self.period_id, "period_id")
        _text(self.entity_id, "entity_id")
        _text(self.label_version_id, "label_version_id")
        outcome = _number(self.forward_return, "forward_return")
        factors = _named_optional_numbers(self.factor_values, "factor_values")
        versions = _named_versions(self.factor_version_ids, "factor_version_ids")
        if {name for name, _ in factors} != {name for name, _ in versions}:
            raise ValueError("factor_values and factor_version_ids must name the same factors")
        mode, factor_trust, label_trust = _validate_statistical_observation(
            data_mode=self.data_mode,
            factor_trust_state=self.factor_trust_state,
            label_trust_state=self.label_trust_state,
            decision_time=self.decision_time,
            factor_available_at=self.factor_available_at,
            label_outcome_at=self.label_outcome_at,
        )
        missing = outcome is None or any(value is None for _, value in factors)
        if missing:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete Fama-MacBeth observation cannot carry missing_reason")
        object.__setattr__(self, "forward_return", outcome)
        object.__setattr__(self, "factor_values", factors)
        object.__setattr__(self, "factor_version_ids", versions)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "factor_trust_state", factor_trust)
        object.__setattr__(self, "label_trust_state", label_trust)

    def factor_value(self, name: str) -> float | None:
        for factor_name, value in self.factor_values:
            if factor_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True)
class FamaMacBethSpec:
    factor_names: tuple[str, ...]
    include_intercept: bool
    minimum_cross_section_size: int
    minimum_period_count: int
    rank_tolerance: float
    formula_version: str
    standard_error_version: str

    def __post_init__(self) -> None:
        names = tuple(_text(value, "factor_names item") for value in self.factor_names)
        if not names:
            raise ValueError("factor_names must not be empty")
        if len(names) != len(set(names)):
            raise ValueError("factor_names must be unique")
        if type(self.include_intercept) is not bool:
            raise TypeError("include_intercept must be a boolean")
        required_rank = len(names) + int(self.include_intercept)
        if (
            type(self.minimum_cross_section_size) is not int
            or self.minimum_cross_section_size < required_rank
        ):
            raise ValueError(
                "minimum_cross_section_size must be an integer at least as large as "
                "the required design rank"
            )
        if type(self.minimum_period_count) is not int or self.minimum_period_count < 2:
            raise ValueError("minimum_period_count must be an integer >= 2")
        tolerance = _number(self.rank_tolerance, "rank_tolerance")
        assert tolerance is not None
        if tolerance <= 0:
            raise ValueError("rank_tolerance must be positive")
        _text(self.formula_version, "formula_version")
        _text(self.standard_error_version, "standard_error_version")
        object.__setattr__(self, "factor_names", names)
        object.__setattr__(self, "rank_tolerance", tolerance)


@dataclass(frozen=True)
class FamaMacBethPeriodResult:
    period_id: str
    status: StatisticStatus
    sample_size: int
    missing_count: int
    design_rank: int
    required_rank: int
    coefficients: tuple[tuple[str, float], ...]
    unavailable_reason: str | None

    def coefficient(self, name: str) -> float:
        for coefficient_name, value in self.coefficients:
            if coefficient_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True)
class FamaMacBethCoefficient:
    name: str
    mean: float
    standard_error: float
    t_statistic: float | None
    period_count: int


@dataclass(frozen=True)
class FamaMacBethResult:
    status: StatisticStatus
    coefficients: tuple[FamaMacBethCoefficient, ...]
    period_results: tuple[FamaMacBethPeriodResult, ...]
    valid_period_count: int
    excluded_period_ids: tuple[str, ...]
    factor_names: tuple[str, ...]
    factor_version_ids: tuple[tuple[str, str], ...]
    label_version_ids: tuple[str, ...]
    minimum_cross_section_size: int
    minimum_period_count: int
    rank_tolerance: float
    formula_version: str
    standard_error_version: str
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus

    def coefficient(self, name: str) -> FamaMacBethCoefficient:
        for value in self.coefficients:
            if value.name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True)
class RegimeSubperiodObservation:
    period_id: str
    value: float | None
    regime_id: str
    subperiod_id: str
    statistic_version_id: str
    data_mode: DataMode
    factor_trust_state: DataTrustState
    label_trust_state: DataTrustState
    decision_time: datetime
    factor_available_at: datetime
    label_outcome_at: datetime
    missing_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("period_id", "regime_id", "subperiod_id", "statistic_version_id"):
            _text(getattr(self, name), name)
        value = _number(self.value, "value")
        mode, factor_trust, label_trust = _validate_statistical_observation(
            data_mode=self.data_mode,
            factor_trust_state=self.factor_trust_state,
            label_trust_state=self.label_trust_state,
            decision_time=self.decision_time,
            factor_available_at=self.factor_available_at,
            label_outcome_at=self.label_outcome_at,
        )
        if value is None:
            _text(self.missing_reason or "", "missing_reason")
        elif self.missing_reason is not None:
            raise ValueError("complete robustness observation cannot carry missing_reason")
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "factor_trust_state", factor_trust)
        object.__setattr__(self, "label_trust_state", label_trust)


@dataclass(frozen=True)
class RegimeSubperiodSpec:
    minimum_observations_per_slice: int
    minimum_regime_count: int
    minimum_subperiod_count: int
    formula_version: str
    regime_definition_version: str
    subperiod_policy_version: str

    def __post_init__(self) -> None:
        if (
            type(self.minimum_observations_per_slice) is not int
            or self.minimum_observations_per_slice < 2
        ):
            raise ValueError("minimum_observations_per_slice must be an integer >= 2")
        if type(self.minimum_regime_count) is not int or self.minimum_regime_count < 1:
            raise ValueError("minimum_regime_count must be a positive integer")
        if type(self.minimum_subperiod_count) is not int or self.minimum_subperiod_count < 1:
            raise ValueError("minimum_subperiod_count must be a positive integer")
        _text(self.formula_version, "formula_version")
        _text(self.regime_definition_version, "regime_definition_version")
        _text(self.subperiod_policy_version, "subperiod_policy_version")


@dataclass(frozen=True)
class RobustnessSliceResult:
    dimension: str
    slice_id: str
    status: StatisticStatus
    sample_size: int
    missing_count: int
    mean: float | None
    standard_deviation: float | None
    unavailable_reason: str | None


@dataclass(frozen=True)
class RegimeSubperiodResult:
    status: StatisticStatus
    overall_mean: float | None
    sample_size: int
    missing_count: int
    regime_slices: tuple[RobustnessSliceResult, ...]
    subperiod_slices: tuple[RobustnessSliceResult, ...]
    regime_sign_consistency_ratio: float | None
    subperiod_sign_consistency_ratio: float | None
    statistic_version_ids: tuple[str, ...]
    minimum_observations_per_slice: int
    minimum_regime_count: int
    minimum_subperiod_count: int
    formula_version: str
    regime_definition_version: str
    subperiod_policy_version: str
    data_mode: DataMode
    historical_eligible: bool
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus

    def slice(self, dimension: str, slice_id: str) -> RobustnessSliceResult:
        if dimension == "regime":
            values = self.regime_slices
        elif dimension == "subperiod":
            values = self.subperiod_slices
        else:
            raise KeyError(dimension)
        for value in values:
            if value.slice_id == slice_id:
                return value
        raise KeyError(slice_id)


def _warnings(data_mode: DataMode, excluded_count: int = 0) -> tuple[str, ...]:
    values: list[str] = []
    if data_mode is DataMode.CURRENT_RESEARCH:
        values.append("current_research statistic is diagnostic and not a historical result")
    if excluded_count:
        values.append(f"{excluded_count} incomplete or invalid slices were excluded")
    return tuple(values)


def _matrix_rank(matrix: Sequence[Sequence[float]], tolerance: float) -> int:
    if not matrix:
        return 0
    working = [list(row) for row in matrix]
    row_count = len(working)
    column_count = len(working[0])
    scale = max(1.0, max(abs(value) for row in working for value in row))
    threshold = tolerance * scale
    rank = 0
    for column in range(column_count):
        pivot = max(range(rank, row_count), key=lambda row: abs(working[row][column]))
        if abs(working[pivot][column]) <= threshold:
            continue
        working[rank], working[pivot] = working[pivot], working[rank]
        pivot_value = working[rank][column]
        for row in range(rank + 1, row_count):
            multiplier = working[row][column] / pivot_value
            for index in range(column, column_count):
                working[row][index] -= multiplier * working[rank][index]
        rank += 1
        if rank == row_count:
            break
    return rank


def _solve_square(
    matrix: Sequence[Sequence[float]], vector: Sequence[float], tolerance: float
) -> tuple[float, ...]:
    size = len(matrix)
    augmented = [list(row) + [float(vector[index])] for index, row in enumerate(matrix)]
    scale = max(1.0, max(abs(value) for row in matrix for value in row))
    threshold = tolerance * scale
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) <= threshold:
            raise ArithmeticError("normal equation is singular at the configured tolerance")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        for index in range(column, size + 1):
            augmented[column][index] /= pivot_value
        for row in range(size):
            if row == column:
                continue
            multiplier = augmented[row][column]
            for index in range(column, size + 1):
                augmented[row][index] -= multiplier * augmented[column][index]
    return tuple(augmented[index][-1] for index in range(size))


def _ordinary_least_squares(
    design: Sequence[Sequence[float]],
    outcomes: Sequence[float],
    tolerance: float,
) -> tuple[float, ...]:
    columns = len(design[0])
    cross_product = [
        [math.fsum(row[left] * row[right] for row in design) for right in range(columns)]
        for left in range(columns)
    ]
    projected = [
        math.fsum(row[column] * outcome for row, outcome in zip(design, outcomes))
        for column in range(columns)
    ]
    return _solve_square(cross_product, projected, tolerance)


def _validate_mode(
    rows: Sequence[FamaMacBethObservation | RegimeSubperiodObservation],
    data_mode: DataMode,
) -> None:
    for row in rows:
        if row.data_mode is not data_mode:
            raise PermissionError("current observations cannot be relabelled as historical results")
        if data_mode is DataMode.STRICT_HISTORICAL and (
            row.factor_trust_state is not DataTrustState.PIT_VERIFIED
            or row.label_trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise PermissionError("strict_historical statistics require pit_verified inputs")


def fama_macbeth(
    observations: Sequence[FamaMacBethObservation],
    *,
    spec: FamaMacBethSpec,
    data_mode: DataMode,
) -> FamaMacBethResult:
    if not isinstance(spec, FamaMacBethSpec):
        raise TypeError("spec must be FamaMacBethSpec")
    rows = tuple(observations)
    if any(not isinstance(row, FamaMacBethObservation) for row in rows):
        raise TypeError("observations must contain FamaMacBethObservation values")
    mode = DataMode(data_mode)
    _validate_mode(rows, mode)
    identities = tuple((row.period_id, row.entity_id) for row in rows)
    if len(identities) != len(set(identities)):
        raise ValueError("period_id and entity_id pairs must be unique")
    expected_names = set(spec.factor_names)
    if any({name for name, _ in row.factor_values} != expected_names for row in rows):
        raise ValueError("every observation must contain exactly the configured factors")

    versions_by_factor: list[tuple[str, str]] = []
    for factor_name in spec.factor_names:
        versions = {
            version
            for row in rows
            for name, version in row.factor_version_ids
            if name == factor_name
        }
        if len(versions) > 1:
            raise ValueError(f"factor {factor_name!r} must freeze one version")
        if versions:
            versions_by_factor.append((factor_name, next(iter(versions))))
    label_versions = tuple(sorted({row.label_version_id for row in rows}))
    if len(label_versions) > 1:
        raise ValueError("Fama-MacBeth observations must freeze one label version")

    grouped: dict[str, list[FamaMacBethObservation]] = {}
    for row in rows:
        grouped.setdefault(row.period_id, []).append(row)
    required_rank = len(spec.factor_names) + int(spec.include_intercept)
    coefficient_names = (("intercept",) if spec.include_intercept else ()) + spec.factor_names
    period_results: list[FamaMacBethPeriodResult] = []
    ordered_periods = sorted(
        grouped.items(),
        key=lambda item: (
            min(row.decision_time for row in item[1]),
            item[0],
        ),
    )
    for period_id, unordered_period_rows in ordered_periods:
        period_rows = tuple(
            sorted(unordered_period_rows, key=lambda row: row.entity_id)
        )
        if len({row.decision_time for row in period_rows}) > 1:
            raise ValueError(f"period {period_id!r} must share one decision_time")
        if len({row.label_outcome_at for row in period_rows}) > 1:
            raise ValueError(f"period {period_id!r} must share one label outcome time")
        complete = tuple(
            row
            for row in period_rows
            if row.forward_return is not None
            and all(value is not None for _, value in row.factor_values)
        )
        missing_count = len(period_rows) - len(complete)
        design = tuple(
            tuple(
                ([1.0] if spec.include_intercept else [])
                + [_present(row.factor_value(name)) for name in spec.factor_names]
            )
            for row in complete
        )
        rank = _matrix_rank(design, spec.rank_tolerance)
        reason: str | None = None
        coefficients: tuple[tuple[str, float], ...] = ()
        if len(complete) < spec.minimum_cross_section_size:
            reason = (
                f"sample_size={len(complete)} is below minimum_cross_section_size="
                f"{spec.minimum_cross_section_size}"
            )
        elif rank < required_rank:
            reason = f"design_rank={rank} is below required_rank={required_rank}"
        else:
            outcomes = tuple(_present(row.forward_return) for row in complete)
            try:
                estimates = _ordinary_least_squares(design, outcomes, spec.rank_tolerance)
            except ArithmeticError as error:
                reason = str(error)
            else:
                coefficients = tuple(zip(coefficient_names, estimates))
        period_results.append(
            FamaMacBethPeriodResult(
                period_id=period_id,
                status=(
                    StatisticStatus.QUANTIFIED if coefficients else StatisticStatus.UNAVAILABLE
                ),
                sample_size=len(complete),
                missing_count=missing_count,
                design_rank=rank,
                required_rank=required_rank,
                coefficients=coefficients,
                unavailable_reason=reason,
            )
        )

    valid = tuple(
        result for result in period_results if result.status is StatisticStatus.QUANTIFIED
    )
    excluded = tuple(
        result.period_id
        for result in period_results
        if result.status is StatisticStatus.UNAVAILABLE
    )
    aggregates: tuple[FamaMacBethCoefficient, ...] = ()
    unavailable_reason: str | None = None
    if len(valid) < spec.minimum_period_count:
        unavailable_reason = (
            f"valid_period_count={len(valid)} is below minimum_period_count="
            f"{spec.minimum_period_count}"
        )
    else:
        coefficient_results: list[FamaMacBethCoefficient] = []
        for name in coefficient_names:
            estimates = tuple(result.coefficient(name) for result in valid)
            mean = math.fsum(estimates) / len(estimates)
            sample_variance = math.fsum((value - mean) ** 2 for value in estimates) / (
                len(estimates) - 1
            )
            standard_error = math.sqrt(sample_variance / len(estimates))
            coefficient_results.append(
                FamaMacBethCoefficient(
                    name=name,
                    mean=mean,
                    standard_error=standard_error,
                    t_statistic=(mean / standard_error if standard_error > 0 else None),
                    period_count=len(estimates),
                )
            )
        aggregates = tuple(coefficient_results)
    return FamaMacBethResult(
        status=(StatisticStatus.QUANTIFIED if aggregates else StatisticStatus.UNAVAILABLE),
        coefficients=aggregates,
        period_results=tuple(period_results),
        valid_period_count=len(valid),
        excluded_period_ids=excluded,
        factor_names=spec.factor_names,
        factor_version_ids=tuple(versions_by_factor),
        label_version_ids=label_versions,
        minimum_cross_section_size=spec.minimum_cross_section_size,
        minimum_period_count=spec.minimum_period_count,
        rank_tolerance=spec.rank_tolerance,
        formula_version=spec.formula_version,
        standard_error_version=spec.standard_error_version,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=unavailable_reason,
        warnings=_warnings(mode, len(excluded)),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


def _slice_results(
    rows: tuple[RegimeSubperiodObservation, ...],
    *,
    dimension: str,
    minimum_sample_size: int,
) -> tuple[RobustnessSliceResult, ...]:
    grouped: dict[str, list[RegimeSubperiodObservation]] = {}
    for row in rows:
        slice_id = row.regime_id if dimension == "regime" else row.subperiod_id
        grouped.setdefault(slice_id, []).append(row)
    results: list[RobustnessSliceResult] = []
    for slice_id in sorted(grouped):
        slice_rows = sorted(
            grouped[slice_id],
            key=lambda row: (row.decision_time, row.period_id),
        )
        values = tuple(float(row.value) for row in slice_rows if row.value is not None)
        missing_count = len(slice_rows) - len(values)
        reason: str | None = None
        mean = standard_deviation = None
        if len(values) < minimum_sample_size:
            reason = (
                f"sample_size={len(values)} is below minimum_observations_per_slice="
                f"{minimum_sample_size}"
            )
        else:
            mean = math.fsum(values) / len(values)
            variance = math.fsum((value - mean) ** 2 for value in values) / (len(values) - 1)
            standard_deviation = math.sqrt(variance)
        results.append(
            RobustnessSliceResult(
                dimension=dimension,
                slice_id=slice_id,
                status=(
                    StatisticStatus.QUANTIFIED if mean is not None else StatisticStatus.UNAVAILABLE
                ),
                sample_size=len(values),
                missing_count=missing_count,
                mean=mean,
                standard_deviation=standard_deviation,
                unavailable_reason=reason,
            )
        )
    return tuple(results)


def _sign_consistency(
    slices: Sequence[RobustnessSliceResult],
    overall_mean: float,
) -> float:
    def sign(value: float) -> int:
        return (value > 0) - (value < 0)

    overall_sign = sign(overall_mean)
    matching = sum(sign(value.mean) == overall_sign for value in slices if value.mean is not None)
    return matching / len(slices)


def regime_subperiod_robustness(
    observations: Sequence[RegimeSubperiodObservation],
    *,
    spec: RegimeSubperiodSpec,
    data_mode: DataMode,
) -> RegimeSubperiodResult:
    if not isinstance(spec, RegimeSubperiodSpec):
        raise TypeError("spec must be RegimeSubperiodSpec")
    rows = tuple(observations)
    if any(not isinstance(row, RegimeSubperiodObservation) for row in rows):
        raise TypeError("observations must contain RegimeSubperiodObservation values")
    mode = DataMode(data_mode)
    _validate_mode(rows, mode)
    rows = tuple(sorted(rows, key=lambda row: (row.decision_time, row.period_id)))
    period_ids = tuple(row.period_id for row in rows)
    if len(period_ids) != len(set(period_ids)):
        raise ValueError("robustness period_id values must be unique")
    statistic_versions = tuple(sorted({row.statistic_version_id for row in rows}))
    if len(statistic_versions) > 1:
        raise ValueError("robustness observations must freeze one statistic version")

    regime_slices = _slice_results(
        rows,
        dimension="regime",
        minimum_sample_size=spec.minimum_observations_per_slice,
    )
    subperiod_slices = _slice_results(
        rows,
        dimension="subperiod",
        minimum_sample_size=spec.minimum_observations_per_slice,
    )
    complete_values = tuple(float(row.value) for row in rows if row.value is not None)
    missing_count = len(rows) - len(complete_values)
    reasons: list[str] = []
    if len(regime_slices) < spec.minimum_regime_count:
        reasons.append(
            f"regime_count={len(regime_slices)} is below minimum_regime_count="
            f"{spec.minimum_regime_count}"
        )
    if len(subperiod_slices) < spec.minimum_subperiod_count:
        reasons.append(
            f"subperiod_count={len(subperiod_slices)} is below minimum_subperiod_count="
            f"{spec.minimum_subperiod_count}"
        )
    unavailable_slices = tuple(
        value
        for value in (*regime_slices, *subperiod_slices)
        if value.status is StatisticStatus.UNAVAILABLE
    )
    if unavailable_slices:
        reasons.append(f"{len(unavailable_slices)} robustness slices are unavailable")

    overall_mean = regime_ratio = subperiod_ratio = None
    if not reasons and complete_values:
        overall_mean = math.fsum(complete_values) / len(complete_values)
        regime_ratio = _sign_consistency(regime_slices, overall_mean)
        subperiod_ratio = _sign_consistency(subperiod_slices, overall_mean)
    elif not complete_values:
        reasons.append("no complete robustness observations")
    reason = "; ".join(reasons) or None
    return RegimeSubperiodResult(
        status=(
            StatisticStatus.QUANTIFIED if overall_mean is not None else StatisticStatus.UNAVAILABLE
        ),
        overall_mean=overall_mean,
        sample_size=len(complete_values),
        missing_count=missing_count,
        regime_slices=regime_slices,
        subperiod_slices=subperiod_slices,
        regime_sign_consistency_ratio=regime_ratio,
        subperiod_sign_consistency_ratio=subperiod_ratio,
        statistic_version_ids=statistic_versions,
        minimum_observations_per_slice=spec.minimum_observations_per_slice,
        minimum_regime_count=spec.minimum_regime_count,
        minimum_subperiod_count=spec.minimum_subperiod_count,
        formula_version=spec.formula_version,
        regime_definition_version=spec.regime_definition_version,
        subperiod_policy_version=spec.subperiod_policy_version,
        data_mode=mode,
        historical_eligible=mode is DataMode.STRICT_HISTORICAL,
        unavailable_reason=reason,
        warnings=_warnings(mode, len(unavailable_slices)),
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "FamaMacBethCoefficient",
    "FamaMacBethObservation",
    "FamaMacBethPeriodResult",
    "FamaMacBethResult",
    "FamaMacBethSpec",
    "RegimeSubperiodObservation",
    "RegimeSubperiodResult",
    "RegimeSubperiodSpec",
    "RobustnessSliceResult",
    "fama_macbeth",
    "regime_subperiod_robustness",
]
