"""Independent-library cross-checks for the dependency-free P4 statistics.

This adapter is deliberately outside the domain package.  SciPy and
statsmodels are optional research-validation dependencies; missing libraries
produce an explicit unavailable report instead of a silent pass.  Numerical
agreement is evidence about implementation consistency only, never evidence
that a factor is scientifically valid.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from a_share_platform.domain.factor_panel_statistics import (
    FamaMacBethObservation,
    FamaMacBethResult,
    FamaMacBethSpec,
    fama_macbeth,
)
from a_share_platform.domain.factor_statistics import (
    CorrelationKind,
    CorrelationSpec,
    CrossSectionObservation,
    HACNeweyWestSpec,
    StatisticsScientificStatus,
    StatisticStatus,
    TimeSeriesObservation,
    information_coefficient,
    newey_west_mean_test,
)
from a_share_platform.domain.run_context import DataMode

_SCIENTIFIC_WARNING = (
    "independent numerical agreement does not establish factor scientific validity",
)


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _non_negative_number(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a real number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return result


def _present(value: float | None) -> float:
    if value is None:
        raise AssertionError("complete observation unexpectedly contains a missing value")
    return value


class CrossCheckStatus(str, Enum):
    MATCHED = "matched"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CrossCheckSpec:
    absolute_tolerance: float
    relative_tolerance: float
    adapter_version: str

    def __post_init__(self) -> None:
        absolute = _non_negative_number(self.absolute_tolerance, "absolute_tolerance")
        relative = _non_negative_number(self.relative_tolerance, "relative_tolerance")
        if absolute == 0 and relative == 0:
            raise ValueError("at least one cross-check tolerance must be positive")
        _text(self.adapter_version, "adapter_version")
        object.__setattr__(self, "absolute_tolerance", absolute)
        object.__setattr__(self, "relative_tolerance", relative)


@dataclass(frozen=True)
class ReferenceLibraryVersion:
    name: str
    version: str

    def __post_init__(self) -> None:
        _text(self.name, "reference library name")
        _text(self.version, "reference library version")


@dataclass(frozen=True)
class CrossCheckComponent:
    name: str
    primary_value: float
    reference_value: float
    absolute_error: float
    allowed_error: float
    within_tolerance: bool


@dataclass(frozen=True)
class StatisticalCrossCheckReport:
    report_id: str
    statistic_id: str
    status: CrossCheckStatus
    components: tuple[CrossCheckComponent, ...]
    absolute_tolerance: float
    relative_tolerance: float
    adapter_version: str
    primary_formula_versions: tuple[str, ...]
    reference_libraries: tuple[ReferenceLibraryVersion, ...]
    reference_method: str
    input_digest: str
    unavailable_reason: str | None
    warnings: tuple[str, ...]
    scientific_status: StatisticsScientificStatus

    def component(self, name: str) -> CrossCheckComponent:
        for value in self.components:
            if value.name == name:
                return value
        raise KeyError(name)


class _ReferenceUnavailable(RuntimeError):
    pass


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _input_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_reference(root_name: str, module_name: str) -> tuple[Any, Any]:
    try:
        root = importlib.import_module(root_name)
        module = importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError) as error:
        raise _ReferenceUnavailable(
            f"independent reference unavailable: optional dependency {root_name} is not installed"
        ) from error
    return root, module


def _version(root: Any, library_name: str) -> ReferenceLibraryVersion:
    version = getattr(root, "__version__", None)
    if not isinstance(version, str) or not version.strip():
        raise _ReferenceUnavailable(
            f"independent reference unavailable: {library_name} version is not observable"
        )
    return ReferenceLibraryVersion(library_name, version)


def _unavailable_report(
    *,
    statistic_id: str,
    cross_check_spec: CrossCheckSpec,
    primary_formula_versions: tuple[str, ...],
    reference_method: str,
    digest: str,
    reason: str,
) -> StatisticalCrossCheckReport:
    return StatisticalCrossCheckReport(
        report_id=f"cross-check:{statistic_id}:{digest[:20]}:{cross_check_spec.adapter_version}",
        statistic_id=statistic_id,
        status=CrossCheckStatus.UNAVAILABLE,
        components=(),
        absolute_tolerance=cross_check_spec.absolute_tolerance,
        relative_tolerance=cross_check_spec.relative_tolerance,
        adapter_version=cross_check_spec.adapter_version,
        primary_formula_versions=primary_formula_versions,
        reference_libraries=(),
        reference_method=reference_method,
        input_digest=digest,
        unavailable_reason=reason,
        warnings=_SCIENTIFIC_WARNING,
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


def _comparison_report(
    *,
    statistic_id: str,
    cross_check_spec: CrossCheckSpec,
    primary_formula_versions: tuple[str, ...],
    library: ReferenceLibraryVersion,
    reference_method: str,
    digest: str,
    pairs: Sequence[tuple[str, float, float]],
) -> StatisticalCrossCheckReport:
    components: list[CrossCheckComponent] = []
    for name, primary, reference in pairs:
        if not math.isfinite(primary) or not math.isfinite(reference):
            return _unavailable_report(
                statistic_id=statistic_id,
                cross_check_spec=cross_check_spec,
                primary_formula_versions=primary_formula_versions,
                reference_method=reference_method,
                digest=digest,
                reason=f"non-finite numerical value in component {name}",
            )
        absolute_error = abs(primary - reference)
        allowed_error = (
            cross_check_spec.absolute_tolerance
            + cross_check_spec.relative_tolerance * abs(reference)
        )
        components.append(
            CrossCheckComponent(
                name=name,
                primary_value=primary,
                reference_value=reference,
                absolute_error=absolute_error,
                allowed_error=allowed_error,
                within_tolerance=absolute_error <= allowed_error,
            )
        )
    status = (
        CrossCheckStatus.MATCHED
        if components and all(value.within_tolerance for value in components)
        else CrossCheckStatus.MISMATCH
    )
    return StatisticalCrossCheckReport(
        report_id=f"cross-check:{statistic_id}:{digest[:20]}:{cross_check_spec.adapter_version}",
        statistic_id=statistic_id,
        status=status,
        components=tuple(components),
        absolute_tolerance=cross_check_spec.absolute_tolerance,
        relative_tolerance=cross_check_spec.relative_tolerance,
        adapter_version=cross_check_spec.adapter_version,
        primary_formula_versions=primary_formula_versions,
        reference_libraries=(library,),
        reference_method=reference_method,
        input_digest=digest,
        unavailable_reason=None,
        warnings=_SCIENTIFIC_WARNING,
        scientific_status=StatisticsScientificStatus.NOT_EVALUATED,
    )


def cross_check_information_coefficient(
    observations: Sequence[CrossSectionObservation],
    *,
    spec: CorrelationSpec,
    cross_check_spec: CrossCheckSpec,
    data_mode: DataMode,
) -> StatisticalCrossCheckReport:
    rows = tuple(observations)
    primary = information_coefficient(rows, spec=spec, data_mode=data_mode)
    statistic_id = f"information-coefficient:{spec.kind.value}"
    digest = _input_digest(
        {
            "observations": [asdict(value) for value in rows],
            "spec": asdict(spec),
            "data_mode": DataMode(data_mode),
        }
    )
    formula_versions = tuple(
        value for value in (spec.formula_version, spec.rank_version) if value is not None
    )
    method = (
        "scipy.stats.pearsonr"
        if spec.kind is CorrelationKind.PEARSON
        else "scipy.stats.spearmanr with average tie ranks"
    )
    if primary.status is StatisticStatus.UNAVAILABLE or primary.value is None:
        return _unavailable_report(
            statistic_id=statistic_id,
            cross_check_spec=cross_check_spec,
            primary_formula_versions=formula_versions,
            reference_method=method,
            digest=digest,
            reason=f"primary statistic unavailable: {primary.unavailable_reason}",
        )
    complete = tuple(
        value for value in rows if value.score is not None and value.forward_return is not None
    )
    scores = [float(value.score) for value in complete if value.score is not None]
    outcomes = [
        float(value.forward_return) for value in complete if value.forward_return is not None
    ]
    try:
        scipy, scipy_stats = _load_reference("scipy", "scipy.stats")
        calculation = (
            scipy_stats.pearsonr(scores, outcomes)
            if spec.kind is CorrelationKind.PEARSON
            else scipy_stats.spearmanr(scores, outcomes)
        )
        reference = float(calculation.statistic)
        library = _version(scipy, "scipy")
    except _ReferenceUnavailable as error:
        return _unavailable_report(
            statistic_id=statistic_id,
            cross_check_spec=cross_check_spec,
            primary_formula_versions=formula_versions,
            reference_method=method,
            digest=digest,
            reason=str(error),
        )
    return _comparison_report(
        statistic_id=statistic_id,
        cross_check_spec=cross_check_spec,
        primary_formula_versions=formula_versions,
        library=library,
        reference_method=method,
        digest=digest,
        pairs=(("coefficient", primary.value, reference),),
    )


def cross_check_newey_west_mean(
    observations: Sequence[TimeSeriesObservation],
    *,
    spec: HACNeweyWestSpec,
    cross_check_spec: CrossCheckSpec,
    data_mode: DataMode,
) -> StatisticalCrossCheckReport:
    rows = tuple(observations)
    primary = newey_west_mean_test(rows, spec=spec, data_mode=data_mode)
    statistic_id = "newey-west-mean"
    digest = _input_digest(
        {
            "observations": [asdict(value) for value in rows],
            "spec": asdict(spec),
            "data_mode": DataMode(data_mode),
        }
    )
    formula_versions = (spec.formula_version,)
    method = (
        f"statsmodels.api.OLS intercept HAC Bartlett maxlags={spec.max_lag} use_correction=False"
    )
    if primary.status is StatisticStatus.UNAVAILABLE:
        return _unavailable_report(
            statistic_id=statistic_id,
            cross_check_spec=cross_check_spec,
            primary_formula_versions=formula_versions,
            reference_method=method,
            digest=digest,
            reason=f"primary statistic unavailable: {primary.unavailable_reason}",
        )
    primary_values = (
        primary.mean,
        primary.long_run_variance,
        primary.standard_error,
        primary.t_statistic,
    )
    if any(value is None for value in primary_values):
        raise AssertionError("quantified Newey-West result is incomplete")
    values = [float(value.value) for value in rows if value.value is not None]
    try:
        statsmodels, statsmodels_api = _load_reference("statsmodels", "statsmodels.api")
        fitted = statsmodels_api.OLS(values, [[1.0]] * len(values)).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": spec.max_lag, "use_correction": False},
        )
        reference_mean = float(fitted.params[0])
        reference_standard_error = float(fitted.bse[0])
        reference_t = float(fitted.tvalues[0])
        reference_long_run_variance = reference_standard_error**2 * len(values)
        library = _version(statsmodels, "statsmodels")
    except _ReferenceUnavailable as error:
        return _unavailable_report(
            statistic_id=statistic_id,
            cross_check_spec=cross_check_spec,
            primary_formula_versions=formula_versions,
            reference_method=method,
            digest=digest,
            reason=str(error),
        )
    assert primary.mean is not None
    assert primary.long_run_variance is not None
    assert primary.standard_error is not None
    assert primary.t_statistic is not None
    return _comparison_report(
        statistic_id=statistic_id,
        cross_check_spec=cross_check_spec,
        primary_formula_versions=formula_versions,
        library=library,
        reference_method=method,
        digest=digest,
        pairs=(
            ("mean", primary.mean, reference_mean),
            (
                "long_run_variance",
                primary.long_run_variance,
                reference_long_run_variance,
            ),
            ("standard_error", primary.standard_error, reference_standard_error),
            ("t_statistic", primary.t_statistic, reference_t),
        ),
    )


def _fama_reference_pairs(
    rows: tuple[FamaMacBethObservation, ...],
    spec: FamaMacBethSpec,
    primary: FamaMacBethResult,
    statsmodels_api: Any,
) -> tuple[tuple[str, float, float], ...]:
    coefficient_names = (
        ("intercept", *spec.factor_names) if spec.include_intercept else spec.factor_names
    )
    grouped: dict[str, list[FamaMacBethObservation]] = {}
    for row in rows:
        grouped.setdefault(row.period_id, []).append(row)
    reference_by_period: dict[str, dict[str, float]] = {}
    pairs: list[tuple[str, float, float]] = []
    for period_result in primary.period_results:
        if period_result.status is StatisticStatus.UNAVAILABLE:
            continue
        complete = tuple(
            sorted(
                (
                    row
                    for row in grouped[period_result.period_id]
                    if row.forward_return is not None
                    and all(value is not None for _, value in row.factor_values)
                ),
                key=lambda row: row.entity_id,
            )
        )
        design = [
            ([1.0] if spec.include_intercept else [])
            + [_present(row.factor_value(name)) for name in spec.factor_names]
            for row in complete
        ]
        outcomes = [_present(row.forward_return) for row in complete]
        fitted = statsmodels_api.OLS(outcomes, design).fit()
        estimates = {name: float(value) for name, value in zip(coefficient_names, fitted.params)}
        reference_by_period[period_result.period_id] = estimates
        pairs.extend(
            (
                f"{period_result.period_id}.{name}",
                period_result.coefficient(name),
                estimates[name],
            )
            for name in coefficient_names
        )
    for name in coefficient_names:
        references = tuple(
            reference_by_period[period_result.period_id][name]
            for period_result in primary.period_results
            if period_result.status is StatisticStatus.QUANTIFIED
        )
        reference_mean = math.fsum(references) / len(references)
        reference_variance = math.fsum((value - reference_mean) ** 2 for value in references) / (
            len(references) - 1
        )
        reference_standard_error = math.sqrt(reference_variance / len(references))
        coefficient = primary.coefficient(name)
        pairs.extend(
            (
                (f"aggregate.{name}.mean", coefficient.mean, reference_mean),
                (
                    f"aggregate.{name}.standard_error",
                    coefficient.standard_error,
                    reference_standard_error,
                ),
            )
        )
        if coefficient.t_statistic is not None and reference_standard_error > 0:
            pairs.append(
                (
                    f"aggregate.{name}.t_statistic",
                    coefficient.t_statistic,
                    reference_mean / reference_standard_error,
                )
            )
    return tuple(pairs)


def cross_check_fama_macbeth(
    observations: Sequence[FamaMacBethObservation],
    *,
    spec: FamaMacBethSpec,
    cross_check_spec: CrossCheckSpec,
    data_mode: DataMode,
) -> StatisticalCrossCheckReport:
    rows = tuple(observations)
    primary = fama_macbeth(rows, spec=spec, data_mode=data_mode)
    statistic_id = "fama-macbeth"
    digest = _input_digest(
        {
            "observations": [asdict(value) for value in rows],
            "spec": asdict(spec),
            "data_mode": DataMode(data_mode),
        }
    )
    formula_versions = (spec.formula_version, spec.standard_error_version)
    method = "statsmodels.api.OLS per period; arithmetic mean and sample SD/sqrt(periods)"
    if primary.status is StatisticStatus.UNAVAILABLE:
        return _unavailable_report(
            statistic_id=statistic_id,
            cross_check_spec=cross_check_spec,
            primary_formula_versions=formula_versions,
            reference_method=method,
            digest=digest,
            reason=f"primary statistic unavailable: {primary.unavailable_reason}",
        )
    try:
        statsmodels, statsmodels_api = _load_reference("statsmodels", "statsmodels.api")
        pairs = _fama_reference_pairs(rows, spec, primary, statsmodels_api)
        library = _version(statsmodels, "statsmodels")
    except _ReferenceUnavailable as error:
        return _unavailable_report(
            statistic_id=statistic_id,
            cross_check_spec=cross_check_spec,
            primary_formula_versions=formula_versions,
            reference_method=method,
            digest=digest,
            reason=str(error),
        )
    return _comparison_report(
        statistic_id=statistic_id,
        cross_check_spec=cross_check_spec,
        primary_formula_versions=formula_versions,
        library=library,
        reference_method=method,
        digest=digest,
        pairs=pairs,
    )


__all__ = [
    "CrossCheckComponent",
    "CrossCheckSpec",
    "CrossCheckStatus",
    "ReferenceLibraryVersion",
    "StatisticalCrossCheckReport",
    "cross_check_fama_macbeth",
    "cross_check_information_coefficient",
    "cross_check_newey_west_mean",
]
