"""Deterministic Decimal execution for versioned cross-sectional transforms.

These implementations are reproducible baselines, not claims of scientific
optimality. Quantiles use the explicitly named ``(n - 1) * p`` linear-rank
interpolation. Neutralization omits the lexicographically first industry and
uses an intercept, the remaining industry dummies, and identity Size in a
fixed column order.

All arithmetic runs in a local Decimal context so callers cannot change results
through process-global precision or rounding settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from enum import Enum

from .features import (
    FeatureCalculationStatus,
    NeutralizationExposure,
    NeutralizationSpec,
    StandardizationSpec,
    WinsorizationSpec,
)

FEATURE_TRANSFORM_DECIMAL_PRECISION = 50
FEATURE_TRANSFORM_DECIMAL_ROUNDING = ROUND_HALF_EVEN

_WINSOR_METHOD = "cross-sectional-quantile"
_WINSOR_INTERPOLATION = "linear-rank-n-minus-one-v1"
_STANDARDIZATION_METHOD = "cross-sectional-zscore"
_NEUTRALIZATION_METHOD = "cross-sectional-linear-residual"
_INDUSTRY_BASELINE = "lexicographically-first"
_SIZE_TRANSFORM = "identity"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _decimal(value: Decimal, field_name: str) -> Decimal:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return value


def _decimal_parameter(value: str, field_name: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be a finite Decimal string") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _integer_parameter(value: str, field_name: str, *, minimum: int) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError(f"{field_name} must be an integer string")
    result = int(value)
    if result < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return result


def _strict_parameters(
    values: tuple[tuple[str, str], ...],
    *,
    expected: frozenset[str],
    transform_name: str,
) -> dict[str, str]:
    parameters = dict(values)
    actual = set(parameters)
    unknown = tuple(sorted(actual - expected))
    missing = tuple(sorted(expected - actual))
    if unknown:
        raise ValueError(
            f"unknown {transform_name} parameters: {', '.join(unknown)}"
        )
    if missing:
        raise ValueError(
            f"missing {transform_name} parameters: {', '.join(missing)}"
        )
    return parameters


class TransformStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CrossSectionRow:
    entity_id: str
    value: Decimal | None
    industry_code: str | None = None
    size_exposure: Decimal | None = None

    def __post_init__(self) -> None:
        _text(self.entity_id, "entity_id")
        if self.value is not None:
            _decimal(self.value, "value")
        if self.industry_code is not None:
            _text(self.industry_code, "industry_code")
        if self.size_exposure is not None:
            _decimal(self.size_exposure, "size_exposure")


@dataclass(frozen=True)
class _RegressionRow:
    entity_id: str
    value: Decimal
    industry_code: str
    size_exposure: Decimal


@dataclass(frozen=True)
class TransformedValue:
    entity_id: str
    status: FeatureCalculationStatus
    value: Decimal | None
    reason: str | None

    def __post_init__(self) -> None:
        _text(self.entity_id, "entity_id")
        status = FeatureCalculationStatus(self.status)
        object.__setattr__(self, "status", status)
        if status is FeatureCalculationStatus.QUANTIFIED:
            if self.value is None:
                raise ValueError("quantified transformed value requires a value")
            _decimal(self.value, "value")
            if self.reason is not None:
                raise ValueError("quantified transformed value cannot carry a reason")
        else:
            if self.value is not None:
                raise ValueError("unavailable transformed value cannot carry a value")
            _text(self.reason or "", "unavailable reason")


@dataclass(frozen=True)
class WinsorizationResult:
    status: TransformStatus
    method: str
    version: str
    values: tuple[TransformedValue, ...]
    sample_size: int
    reason: str | None
    lower_bound: Decimal | None
    upper_bound: Decimal | None


@dataclass(frozen=True)
class StandardizationResult:
    status: TransformStatus
    method: str
    version: str
    values: tuple[TransformedValue, ...]
    sample_size: int
    reason: str | None
    mean: Decimal | None
    standard_deviation: Decimal | None


@dataclass(frozen=True)
class NeutralizationResult:
    status: TransformStatus
    method: str
    version: str
    values: tuple[TransformedValue, ...]
    sample_size: int
    reason: str | None
    industry_baseline: str | None
    coefficients: tuple[tuple[str, Decimal], ...]


def _rows(values: tuple[CrossSectionRow, ...]) -> tuple[CrossSectionRow, ...]:
    rows = tuple(values)
    if not rows:
        raise ValueError("cross section must not be empty")
    if any(not isinstance(value, CrossSectionRow) for value in rows):
        raise TypeError("cross section must contain CrossSectionRow values")
    entity_ids = tuple(value.entity_id for value in rows)
    if len(entity_ids) != len(set(entity_ids)):
        raise ValueError("cross section entity_ids must be unique")
    return rows


def _global_unavailable(
    rows: tuple[CrossSectionRow, ...],
    reason: str,
) -> tuple[TransformedValue, ...]:
    return tuple(
        TransformedValue(
            entity_id=row.entity_id,
            status=FeatureCalculationStatus.UNAVAILABLE,
            value=None,
            reason=reason,
        )
        for row in rows
    )


def _partial_values(
    rows: tuple[CrossSectionRow, ...],
    calculated: dict[str, Decimal],
    missing_reasons: dict[str, str],
) -> tuple[TransformedValue, ...]:
    output: list[TransformedValue] = []
    for row in rows:
        if row.entity_id in calculated:
            output.append(
                TransformedValue(
                    entity_id=row.entity_id,
                    status=FeatureCalculationStatus.QUANTIFIED,
                    value=calculated[row.entity_id],
                    reason=None,
                )
            )
        else:
            output.append(
                TransformedValue(
                    entity_id=row.entity_id,
                    status=FeatureCalculationStatus.UNAVAILABLE,
                    value=None,
                    reason=missing_reasons[row.entity_id],
                )
            )
    return tuple(output)


def _quantile_linear_rank_n_minus_one(
    sorted_values: tuple[Decimal, ...],
    probability: Decimal,
) -> Decimal:
    """Return x[(n-1)p] using deterministic linear interpolation.

    The integer part selects the lower zero-based rank and the fractional part
    linearly interpolates to the next rank. This convention is a reproducible
    baseline selected by method name, not a claim that it is scientifically
    preferable to other quantile definitions.
    """

    if len(sorted_values) == 1:
        return sorted_values[0]
    with localcontext() as context:
        context.prec = FEATURE_TRANSFORM_DECIMAL_PRECISION
        context.rounding = FEATURE_TRANSFORM_DECIMAL_ROUNDING
        rank = Decimal(len(sorted_values) - 1) * probability
        lower_index = int(rank)
        fraction = rank - Decimal(lower_index)
        if fraction == 0:
            return sorted_values[lower_index]
        upper_index = lower_index + 1
        lower = sorted_values[lower_index]
        upper = sorted_values[upper_index]
        return lower + fraction * (upper - lower)


def execute_winsorization(
    values: tuple[CrossSectionRow, ...],
    spec: WinsorizationSpec,
) -> WinsorizationResult:
    rows = _rows(values)
    if not isinstance(spec, WinsorizationSpec):
        raise TypeError("spec must be a WinsorizationSpec")
    if spec.method != _WINSOR_METHOD:
        raise ValueError(f"unsupported winsorization method: {spec.method}")
    parameters = _strict_parameters(
        spec.parameters,
        expected=frozenset(
            {"interpolation", "lower", "minimum_observations", "upper"}
        ),
        transform_name="winsorization",
    )
    if parameters["interpolation"] != _WINSOR_INTERPOLATION:
        raise ValueError(
            f"unsupported quantile interpolation: {parameters['interpolation']}"
        )
    lower_probability = _decimal_parameter(parameters["lower"], "lower")
    upper_probability = _decimal_parameter(parameters["upper"], "upper")
    if not Decimal(0) <= lower_probability < upper_probability <= Decimal(1):
        raise ValueError("winsorization quantiles must satisfy 0 <= lower < upper <= 1")
    minimum = _integer_parameter(
        parameters["minimum_observations"],
        "minimum_observations",
        minimum=1,
    )
    observed = tuple(sorted(row.value for row in rows if row.value is not None))
    sample_size = len(observed)
    if sample_size < minimum:
        reason = (
            f"minimum observations not met: required {minimum}, observed {sample_size}"
        )
        return WinsorizationResult(
            status=TransformStatus.UNAVAILABLE,
            method=spec.method,
            version=spec.version,
            values=_global_unavailable(rows, reason),
            sample_size=sample_size,
            reason=reason,
            lower_bound=None,
            upper_bound=None,
        )

    ordered = tuple(sorted(observed))
    lower_bound = _quantile_linear_rank_n_minus_one(ordered, lower_probability)
    upper_bound = _quantile_linear_rank_n_minus_one(ordered, upper_probability)
    calculated = {
        row.entity_id: min(max(row.value, lower_bound), upper_bound)
        for row in rows
        if row.value is not None
    }
    missing_reasons = {
        row.entity_id: "input value is missing" for row in rows if row.value is None
    }
    return WinsorizationResult(
        status=TransformStatus.QUANTIFIED,
        method=spec.method,
        version=spec.version,
        values=_partial_values(rows, calculated, missing_reasons),
        sample_size=sample_size,
        reason=None,
        lower_bound=lower_bound,
        upper_bound=upper_bound,
    )


def execute_standardization(
    values: tuple[CrossSectionRow, ...],
    spec: StandardizationSpec,
) -> StandardizationResult:
    rows = _rows(values)
    if not isinstance(spec, StandardizationSpec):
        raise TypeError("spec must be a StandardizationSpec")
    if spec.method != _STANDARDIZATION_METHOD:
        raise ValueError(f"unsupported standardization method: {spec.method}")
    parameters = _strict_parameters(
        spec.parameters,
        expected=frozenset({"ddof", "minimum_observations"}),
        transform_name="standardization",
    )
    ddof = _integer_parameter(parameters["ddof"], "ddof", minimum=0)
    minimum = _integer_parameter(
        parameters["minimum_observations"],
        "minimum_observations",
        minimum=1,
    )
    observed = tuple(sorted(row.value for row in rows if row.value is not None))
    sample_size = len(observed)
    if sample_size < minimum:
        reason = (
            f"minimum observations not met: required {minimum}, observed {sample_size}"
        )
        return StandardizationResult(
            status=TransformStatus.UNAVAILABLE,
            method=spec.method,
            version=spec.version,
            values=_global_unavailable(rows, reason),
            sample_size=sample_size,
            reason=reason,
            mean=None,
            standard_deviation=None,
        )
    if sample_size - ddof <= 0:
        reason = f"ddof {ddof} leaves no positive variance denominator"
        return StandardizationResult(
            status=TransformStatus.UNAVAILABLE,
            method=spec.method,
            version=spec.version,
            values=_global_unavailable(rows, reason),
            sample_size=sample_size,
            reason=reason,
            mean=None,
            standard_deviation=None,
        )

    with localcontext() as context:
        context.prec = FEATURE_TRANSFORM_DECIMAL_PRECISION
        context.rounding = FEATURE_TRANSFORM_DECIMAL_ROUNDING
        mean = sum(observed, Decimal(0)) / Decimal(sample_size)
        variance = sum(((value - mean) ** 2 for value in observed), Decimal(0)) / Decimal(
            sample_size - ddof
        )
        standard_deviation = variance.sqrt()
        if standard_deviation == 0:
            reason = "constant cross section has zero standard deviation"
            return StandardizationResult(
                status=TransformStatus.UNAVAILABLE,
                method=spec.method,
                version=spec.version,
                values=_global_unavailable(rows, reason),
                sample_size=sample_size,
                reason=reason,
                mean=mean,
                standard_deviation=standard_deviation,
            )
        calculated = {
            row.entity_id: (row.value - mean) / standard_deviation
            for row in rows
            if row.value is not None
        }
    missing_reasons = {
        row.entity_id: "input value is missing" for row in rows if row.value is None
    }
    return StandardizationResult(
        status=TransformStatus.QUANTIFIED,
        method=spec.method,
        version=spec.version,
        values=_partial_values(rows, calculated, missing_reasons),
        sample_size=sample_size,
        reason=None,
        mean=mean,
        standard_deviation=standard_deviation,
    )


def _solve_linear_system(
    matrix: list[list[Decimal]],
    vector: list[Decimal],
) -> tuple[Decimal, ...] | None:
    """Solve by deterministic partial-pivot Gaussian elimination."""

    size = len(vector)
    augmented = [matrix[index][:] + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if augmented[pivot][column] == 0:
            return None
        if pivot != column:
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        augmented[column] = [value / pivot_value for value in augmented[column]]
        for row_index in range(size):
            if row_index == column:
                continue
            multiplier = augmented[row_index][column]
            if multiplier == 0:
                continue
            augmented[row_index] = [
                current - multiplier * pivot_value
                for current, pivot_value in zip(
                    augmented[row_index], augmented[column], strict=True
                )
            ]
    return tuple(row[-1] for row in augmented)


def execute_neutralization(
    values: tuple[CrossSectionRow, ...],
    spec: NeutralizationSpec,
) -> NeutralizationResult:
    rows = _rows(values)
    if not isinstance(spec, NeutralizationSpec):
        raise TypeError("spec must be a NeutralizationSpec")
    if spec.method != _NEUTRALIZATION_METHOD:
        raise ValueError(f"unsupported neutralization method: {spec.method}")
    if set(spec.exposures) != {
        NeutralizationExposure.INDUSTRY,
        NeutralizationExposure.SIZE,
    }:
        raise ValueError("neutralization requires exactly industry and size exposures")
    parameters = _strict_parameters(
        spec.parameters,
        expected=frozenset(
            {"industry_baseline", "minimum_observations", "size_transform"}
        ),
        transform_name="neutralization",
    )
    if parameters["industry_baseline"] != _INDUSTRY_BASELINE:
        raise ValueError(
            f"unsupported industry baseline: {parameters['industry_baseline']}"
        )
    if parameters["size_transform"] != _SIZE_TRANSFORM:
        raise ValueError(f"unsupported size transform: {parameters['size_transform']}")
    minimum = _integer_parameter(
        parameters["minimum_observations"],
        "minimum_observations",
        minimum=1,
    )

    eligible = tuple(
        sorted(
            (
                _RegressionRow(
                    entity_id=row.entity_id,
                    value=row.value,
                    industry_code=row.industry_code,
                    size_exposure=row.size_exposure,
                )
                for row in rows
                if row.value is not None
                and row.industry_code is not None
                and row.size_exposure is not None
            ),
            key=lambda row: row.entity_id,
        )
    )
    sample_size = len(eligible)
    if sample_size < minimum:
        reason = (
            f"minimum observations not met: required {minimum}, observed {sample_size}"
        )
        return NeutralizationResult(
            status=TransformStatus.UNAVAILABLE,
            method=spec.method,
            version=spec.version,
            values=_global_unavailable(rows, reason),
            sample_size=sample_size,
            reason=reason,
            industry_baseline=None,
            coefficients=(),
        )

    industries = tuple(sorted({row.industry_code for row in eligible}))
    baseline = industries[0]
    dummy_industries = industries[1:]
    column_names = ("intercept", *(f"industry:{value}" for value in dummy_industries), "size")
    regressor_count = len(column_names)
    if sample_size <= regressor_count:
        reason = (
            "neutralization requires more observations than regressors: "
            f"observed {sample_size}, regressors {regressor_count}"
        )
        return NeutralizationResult(
            status=TransformStatus.UNAVAILABLE,
            method=spec.method,
            version=spec.version,
            values=_global_unavailable(rows, reason),
            sample_size=sample_size,
            reason=reason,
            industry_baseline=baseline,
            coefficients=(),
        )

    design = [
        [
            Decimal(1),
            *(Decimal(row.industry_code == industry) for industry in dummy_industries),
            row.size_exposure,
        ]
        for row in eligible
    ]
    targets = [row.value for row in eligible]
    with localcontext() as context:
        context.prec = FEATURE_TRANSFORM_DECIMAL_PRECISION
        context.rounding = FEATURE_TRANSFORM_DECIMAL_ROUNDING
        normal_matrix = [
            [
                sum(
                    (design[row][left] * design[row][right] for row in range(sample_size)),
                    Decimal(0),
                )
                for right in range(regressor_count)
            ]
            for left in range(regressor_count)
        ]
        normal_vector = [
            sum(
                (
                    design[row][column] * targets[row]
                    for row in range(sample_size)
                ),
                Decimal(0),
            )
            for column in range(regressor_count)
        ]
        solved = _solve_linear_system(normal_matrix, normal_vector)
        if solved is None:
            reason = "neutralization design matrix is singular"
            return NeutralizationResult(
                status=TransformStatus.UNAVAILABLE,
                method=spec.method,
                version=spec.version,
                values=_global_unavailable(rows, reason),
                sample_size=sample_size,
                reason=reason,
                industry_baseline=baseline,
                coefficients=(),
            )
        calculated = {
            row.entity_id: row.value
            - sum(
                (coefficient * regressor for coefficient, regressor in zip(solved, design_row, strict=True)),
                Decimal(0),
            )
            for row, design_row in zip(eligible, design, strict=True)
        }

    missing_reasons: dict[str, str] = {}
    for row in rows:
        if row.value is None:
            missing_reasons[row.entity_id] = "input value is missing"
        elif row.industry_code is None:
            missing_reasons[row.entity_id] = "industry_code is missing"
        elif row.size_exposure is None:
            missing_reasons[row.entity_id] = "size_exposure is missing"
    return NeutralizationResult(
        status=TransformStatus.QUANTIFIED,
        method=spec.method,
        version=spec.version,
        values=_partial_values(rows, calculated, missing_reasons),
        sample_size=sample_size,
        reason=None,
        industry_baseline=baseline,
        coefficients=tuple(zip(column_names, solved, strict=True)),
    )


__all__ = [
    "FEATURE_TRANSFORM_DECIMAL_PRECISION",
    "FEATURE_TRANSFORM_DECIMAL_ROUNDING",
    "CrossSectionRow",
    "NeutralizationResult",
    "StandardizationResult",
    "TransformStatus",
    "TransformedValue",
    "WinsorizationResult",
    "execute_neutralization",
    "execute_standardization",
    "execute_winsorization",
]
