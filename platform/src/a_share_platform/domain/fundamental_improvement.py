"""Provider-neutral, scientifically unvalidated Fundamental Improvement V0.

Level, trend, and acceleration stay metric-specific because currency levels and
margin ratios cannot be combined without destroying unit semantics.  Breadth
is the fraction of usable metrics with strictly positive acceleration;
confidence is a transparent input-comparability coverage ratio, not a forecast
probability.  Cross-sectional transforms are deliberately versioned but not
performed by this company-level pure function.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .features import FeatureCalculationStatus
from .metrics import MetricUnit
from .pit import DataTrustState
from .run_context import DataMode

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_QUARTER_ENDS = {(3, 31): 0, (6, 30): 1, (9, 30): 2, (12, 31): 3}


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


def _plain_date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date")
    if (value.month, value.day) not in _QUARTER_ENDS:
        raise ValueError(f"{field_name} must be a calendar quarter end")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _quarter_ordinal(value: date) -> int:
    return value.year * 4 + _QUARTER_ENDS[(value.month, value.day)]


class FundamentalImprovementMetric(str, Enum):
    REVENUE = "revenue"
    PROFIT = "profit"
    MARGIN = "margin"
    CASH_FLOW = "cash_flow"


class ImprovementComparison(str, Enum):
    YOY = "yoy"
    QOQ = "qoq"


class ImprovementWindow(str, Enum):
    TTM = "ttm"
    SINGLE_QUARTER = "single_quarter"


class SeasonalityTreatment(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    YOY_COMPARABLE = "yoy_comparable"
    SEASONALLY_ADJUSTED = "seasonally_adjusted"
    UNCONTROLLED = "uncontrolled"
    UNKNOWN = "unknown"


class BaseEffectTreatment(str, Enum):
    ABSENT = "absent"
    ADJUSTED = "adjusted"
    PRESENT_UNADJUSTED = "present_unadjusted"
    UNKNOWN = "unknown"


class OneOffTreatment(str, Enum):
    EXCLUDED = "excluded"
    ADJUSTED = "adjusted"
    INCLUDED_UNADJUSTED = "included_unadjusted"
    UNKNOWN = "unknown"


class ImprovementResultStatus(str, Enum):
    QUANTIFIED = "quantified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ImprovementScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class ImprovementInputProvenance:
    dataset_version_id: str
    source_version_id: str
    mapping_version_id: str
    metric_definition_id: str
    metric_definition_version: str
    source_fact_ids: tuple[str, ...]
    content_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "dataset_version_id",
            "source_version_id",
            "mapping_version_id",
            "metric_definition_id",
            "metric_definition_version",
        ):
            _text(getattr(self, name), name)
        facts = tuple(self.source_fact_ids)
        hashes = tuple(self.content_hashes)
        if not facts or any(not isinstance(value, str) or not value.strip() for value in facts):
            raise ValueError("source_fact_ids must contain non-empty identifiers")
        if not hashes or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None
            for value in hashes
        ):
            raise ValueError("content_hashes must contain sha256 hashes")
        if len(facts) != len(set(facts)) or len(hashes) != len(set(hashes)):
            raise ValueError("provenance identifiers and hashes must be unique")
        object.__setattr__(self, "source_fact_ids", tuple(sorted(facts)))
        object.__setattr__(self, "content_hashes", tuple(sorted(hashes)))


@dataclass(frozen=True)
class FundamentalImprovementExposures:
    """Risk exposures carried with the result and excluded from the formula."""

    industry_code: str | None
    log_market_cap: Decimal | None
    beta: Decimal | None
    missing_exposure_names: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        if self.industry_code is not None:
            _text(self.industry_code, "industry_code")
        if self.log_market_cap is not None:
            _decimal(self.log_market_cap, "log_market_cap")
        if self.beta is not None:
            _decimal(self.beta, "beta")
        object.__setattr__(
            self,
            "missing_exposure_names",
            tuple(
                name
                for name, value in (
                    ("industry", self.industry_code),
                    ("size", self.log_market_cap),
                    ("beta", self.beta),
                )
                if value is None
            ),
        )


@dataclass(frozen=True)
class FundamentalImprovementInput:
    metric: FundamentalImprovementMetric
    level: Decimal | None
    current_change: Decimal | None
    prior_change: Decimal | None
    level_unit: MetricUnit
    change_unit: MetricUnit
    currency: str | None
    comparison: ImprovementComparison
    window: ImprovementWindow
    current_period_end: date
    current_comparison_period_end: date
    prior_period_end: date
    prior_comparison_period_end: date
    seasonality_treatment: SeasonalityTreatment
    base_effect_treatment: BaseEffectTreatment
    one_off_treatment: OneOffTreatment
    provenance: ImprovementInputProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    unavailable_reasons: tuple[str, ...] = ()
    decision_time: datetime | None = None
    latest_source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        metric = FundamentalImprovementMetric(self.metric)
        object.__setattr__(self, "metric", metric)
        for name in ("level", "current_change", "prior_change"):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name)
        level_unit = MetricUnit(self.level_unit)
        change_unit = MetricUnit(self.change_unit)
        expected_level_unit = (
            MetricUnit.RATIO
            if metric is FundamentalImprovementMetric.MARGIN
            else MetricUnit.CURRENCY
        )
        if level_unit is not expected_level_unit:
            raise ValueError(f"{metric.value} level unit is incompatible")
        if change_unit is not MetricUnit.RATIO:
            raise ValueError("improvement change unit must be ratio")
        if level_unit is MetricUnit.CURRENCY:
            if self.currency is None or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
                raise ValueError("currency level requires a three-letter currency")
        elif self.currency is not None:
            raise ValueError("ratio level must not carry currency")
        object.__setattr__(self, "level_unit", level_unit)
        object.__setattr__(self, "change_unit", change_unit)

        comparison = ImprovementComparison(self.comparison)
        window = ImprovementWindow(self.window)
        seasonality = SeasonalityTreatment(self.seasonality_treatment)
        object.__setattr__(self, "comparison", comparison)
        object.__setattr__(self, "window", window)
        object.__setattr__(self, "seasonality_treatment", seasonality)
        object.__setattr__(
            self,
            "base_effect_treatment",
            BaseEffectTreatment(self.base_effect_treatment),
        )
        object.__setattr__(self, "one_off_treatment", OneOffTreatment(self.one_off_treatment))
        self._validate_periods()
        if window is ImprovementWindow.SINGLE_QUARTER:
            if comparison is ImprovementComparison.QOQ and seasonality is SeasonalityTreatment.YOY_COMPARABLE:
                raise ValueError("qoq single-quarter input cannot claim yoy comparability")
            if comparison is ImprovementComparison.YOY and seasonality is SeasonalityTreatment.NOT_APPLICABLE:
                raise ValueError("single-quarter yoy input must state seasonality treatment")

        if not isinstance(self.provenance, ImprovementInputProvenance):
            raise TypeError("provenance must be ImprovementInputProvenance")
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw inputs cannot enter Fundamental Improvement V0")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical improvement requires pit_verified inputs")
        availability_values = (self.decision_time, self.latest_source_available_at)
        if any(value is None for value in availability_values) and any(
            value is not None for value in availability_values
        ):
            raise ValueError(
                "decision_time and latest_source_available_at must be present together"
            )
        if self.decision_time is not None and self.latest_source_available_at is not None:
            decision_time = _aware(self.decision_time, "decision_time")
            latest_available = _aware(
                self.latest_source_available_at,
                "latest_source_available_at",
            )
            if latest_available > decision_time:
                raise ValueError("available_at cannot exceed decision_time")
        elif mode is DataMode.STRICT_HISTORICAL:
            raise PermissionError(
                "strict_historical improvement requires available_at <= decision_time evidence"
            )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)

        reasons = tuple(self.unavailable_reasons)
        if len(reasons) != len(set(reasons)) or any(
            not isinstance(reason, str) or not reason.strip() for reason in reasons
        ):
            raise ValueError("unavailable_reasons must contain unique non-empty text")
        has_missing = any(
            value is None for value in (self.level, self.current_change, self.prior_change)
        )
        if has_missing and not reasons:
            raise ValueError("missing numeric inputs require unavailable_reasons")
        if not has_missing and reasons:
            raise ValueError("available numeric inputs cannot carry unavailable_reasons")
        object.__setattr__(self, "unavailable_reasons", reasons)

    def _validate_periods(self) -> None:
        current = _plain_date(self.current_period_end, "current_period_end")
        current_comparison = _plain_date(
            self.current_comparison_period_end,
            "current_comparison_period_end",
        )
        prior = _plain_date(self.prior_period_end, "prior_period_end")
        prior_comparison = _plain_date(
            self.prior_comparison_period_end,
            "prior_comparison_period_end",
        )
        if _quarter_ordinal(current) - _quarter_ordinal(prior) != 1:
            raise ValueError("current and prior trend periods must be adjacent quarters")
        if self.comparison is ImprovementComparison.YOY:
            if (
                _quarter_ordinal(current) - _quarter_ordinal(current_comparison) != 4
                or _quarter_ordinal(prior) - _quarter_ordinal(prior_comparison) != 4
            ):
                raise ValueError("yoy inputs require year-earlier comparison periods")
        elif (
            current_comparison != prior
            or _quarter_ordinal(prior) - _quarter_ordinal(prior_comparison) != 1
        ):
            raise ValueError("qoq inputs require adjacent-quarter comparison periods")


@dataclass(frozen=True)
class FundamentalImprovementComponentResult:
    metric: FundamentalImprovementMetric
    status: FeatureCalculationStatus
    level: Decimal | None
    trend: Decimal | None
    acceleration: Decimal | None
    level_unit: MetricUnit
    change_unit: MetricUnit
    currency: str | None
    comparison: ImprovementComparison | None
    window: ImprovementWindow | None
    seasonality_treatment: SeasonalityTreatment | None
    base_effect_treatment: BaseEffectTreatment | None
    one_off_treatment: OneOffTreatment | None
    provenance: ImprovementInputProvenance | None
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", FundamentalImprovementMetric(self.metric))
        status = FeatureCalculationStatus(self.status)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "level_unit", MetricUnit(self.level_unit))
        object.__setattr__(self, "change_unit", MetricUnit(self.change_unit))
        reasons = tuple(self.unavailable_reasons)
        if status is FeatureCalculationStatus.QUANTIFIED:
            for name in ("level", "trend", "acceleration"):
                value = getattr(self, name)
                if value is None:
                    raise ValueError("quantified improvement component requires all values")
                _decimal(value, name)
            if reasons or self.provenance is None:
                raise ValueError("quantified component requires provenance and no missing reason")
        else:
            if any(value is not None for value in (self.level, self.trend, self.acceleration)):
                raise ValueError("unavailable component cannot carry numeric values")
            if not reasons:
                raise ValueError("unavailable component requires reasons")
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class FundamentalImprovementResult:
    status: ImprovementResultStatus
    breadth: Decimal | None
    confidence: Decimal | None
    component_results: tuple[FundamentalImprovementComponentResult, ...]
    unavailable_metrics: tuple[FundamentalImprovementMetric, ...]
    exposures: FundamentalImprovementExposures
    data_mode: DataMode
    historical_eligible: bool
    formula_id: str
    formula_version: str
    definition_hash: str
    input_dataset_version_ids: tuple[str, ...]
    input_content_hashes: tuple[str, ...]
    decision_time: datetime | None
    latest_input_available_at: datetime | None
    warnings: tuple[str, ...]
    scientific_status: ImprovementScientificStatus

    def component(
        self,
        metric: FundamentalImprovementMetric,
    ) -> FundamentalImprovementComponentResult:
        selected = [value for value in self.component_results if value.metric is metric]
        if len(selected) != 1:
            raise LookupError(f"improvement component is unavailable: {metric.value}")
        return selected[0]


@dataclass(frozen=True)
class FundamentalImprovementDefinition:
    factor_id: str
    formula_id: str
    formula_version: str
    missing_policy_version: str
    winsorization_version: str
    standardization_version: str
    neutralization_version: str
    neutralization_exposure_names: tuple[str, ...]
    required_metrics: tuple[FundamentalImprovementMetric, ...]
    scientific_status: ImprovementScientificStatus
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "factor_id",
            "formula_id",
            "formula_version",
            "missing_policy_version",
            "winsorization_version",
            "standardization_version",
            "neutralization_version",
        ):
            _text(getattr(self, name), name)
        metrics = tuple(FundamentalImprovementMetric(value) for value in self.required_metrics)
        if set(metrics) != set(FundamentalImprovementMetric):
            raise ValueError("Improvement V0 requires revenue, profit, margin, and cash flow")
        exposures = tuple(self.neutralization_exposure_names)
        if exposures != ("industry", "size", "beta"):
            raise ValueError("Improvement V0 exposures must be industry, size, and beta")
        scientific = ImprovementScientificStatus(self.scientific_status)
        if scientific is not ImprovementScientificStatus.NOT_EVALUATED:
            raise ValueError("Improvement V0 cannot claim scientific validation")
        object.__setattr__(self, "required_metrics", metrics)
        object.__setattr__(self, "scientific_status", scientific)
        payload = {
            "factor_id": self.factor_id,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "missing_policy_version": self.missing_policy_version,
            "winsorization_version": self.winsorization_version,
            "standardization_version": self.standardization_version,
            "neutralization_version": self.neutralization_version,
            "neutralization_exposures": exposures,
            "required_metrics": [value.value for value in metrics],
            "scientific_status": scientific.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(self, "definition_hash", f"sha256:{hashlib.sha256(encoded).hexdigest()}")

    def calculate(
        self,
        values: Mapping[FundamentalImprovementMetric, FundamentalImprovementInput],
        *,
        exposures: FundamentalImprovementExposures,
        data_mode: DataMode,
    ) -> FundamentalImprovementResult:
        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        if not isinstance(exposures, FundamentalImprovementExposures):
            raise TypeError("exposures must be FundamentalImprovementExposures")
        mode = DataMode(data_mode)
        normalized: dict[FundamentalImprovementMetric, FundamentalImprovementInput] = {}
        for raw_metric, value in values.items():
            metric = FundamentalImprovementMetric(raw_metric)
            if metric in normalized:
                raise ValueError(f"duplicate improvement input: {metric.value}")
            if not isinstance(value, FundamentalImprovementInput):
                raise TypeError(f"improvement input {metric.value} has invalid type")
            if value.metric is not metric:
                raise ValueError(f"improvement input metric mismatch: {metric.value}")
            if mode is DataMode.STRICT_HISTORICAL and value.trust_state is not DataTrustState.PIT_VERIFIED:
                raise PermissionError("strict_historical improvement requires pit_verified inputs")
            if value.data_mode is not mode:
                raise PermissionError(
                    "current_research inputs cannot be relabelled as strict historical results"
                )
            normalized[metric] = value

        components = tuple(
            self._component(metric, normalized.get(metric)) for metric in self.required_metrics
        )
        quantified = tuple(
            value
            for value in components
            if value.status is FeatureCalculationStatus.QUANTIFIED
        )
        unavailable = tuple(
            sorted(
                (
                    value.metric
                    for value in components
                    if value.status is FeatureCalculationStatus.UNAVAILABLE
                ),
                key=lambda value: value.value,
            )
        )
        if not quantified:
            status = ImprovementResultStatus.UNAVAILABLE
            breadth = None
            confidence = None
        else:
            status = (
                ImprovementResultStatus.QUANTIFIED
                if len(quantified) == len(self.required_metrics)
                else ImprovementResultStatus.PARTIAL
            )
            breadth = Decimal(
                sum(value.acceleration > 0 for value in quantified if value.acceleration is not None)
            ) / Decimal(len(quantified))
            confidence = Decimal(len(quantified)) / Decimal(len(self.required_metrics))
        if mode is DataMode.STRICT_HISTORICAL:
            decision_times = {value.decision_time for value in normalized.values()}
            if len(decision_times) != 1:
                raise ValueError("strict_historical inputs must share one decision_time")
            decision_time = next(iter(decision_times))
            assert decision_time is not None
            available_times = tuple(
                value.latest_source_available_at for value in normalized.values()
            )
            assert all(value is not None for value in available_times)
            latest_input_available_at = max(
                value for value in available_times if value is not None
            )
        else:
            decision_time = None
            latest_input_available_at = None
        warnings: list[str] = []
        if mode is DataMode.CURRENT_RESEARCH:
            warnings.append(
                "current_research improvement is a current result, not a historical or PIT result"
            )
        if status is ImprovementResultStatus.PARTIAL:
            warnings.append("partial improvement excludes unavailable metrics without zero filling")
        provenances = tuple(value.provenance for value in normalized.values())
        return FundamentalImprovementResult(
            status=status,
            breadth=breadth,
            confidence=confidence,
            component_results=components,
            unavailable_metrics=unavailable,
            exposures=exposures,
            data_mode=mode,
            historical_eligible=mode is DataMode.STRICT_HISTORICAL,
            formula_id=self.formula_id,
            formula_version=self.formula_version,
            definition_hash=self.definition_hash,
            input_dataset_version_ids=tuple(
                sorted({value.dataset_version_id for value in provenances})
            ),
            input_content_hashes=tuple(
                sorted({item for value in provenances for item in value.content_hashes})
            ),
            decision_time=decision_time,
            latest_input_available_at=latest_input_available_at,
            warnings=tuple(warnings),
            scientific_status=self.scientific_status,
        )

    @staticmethod
    def _component(
        metric: FundamentalImprovementMetric,
        value: FundamentalImprovementInput | None,
    ) -> FundamentalImprovementComponentResult:
        level_unit = (
            MetricUnit.RATIO
            if metric is FundamentalImprovementMetric.MARGIN
            else MetricUnit.CURRENCY
        )
        if value is None:
            return FundamentalImprovementComponentResult(
                metric=metric,
                status=FeatureCalculationStatus.UNAVAILABLE,
                level=None,
                trend=None,
                acceleration=None,
                level_unit=level_unit,
                change_unit=MetricUnit.RATIO,
                currency=None,
                comparison=None,
                window=None,
                seasonality_treatment=None,
                base_effect_treatment=None,
                one_off_treatment=None,
                provenance=None,
                unavailable_reasons=(f"{metric.value} input is missing",),
            )
        reasons = list(value.unavailable_reasons)
        if value.seasonality_treatment in {
            SeasonalityTreatment.UNCONTROLLED,
            SeasonalityTreatment.UNKNOWN,
        }:
            reasons.append(
                f"seasonality is {value.seasonality_treatment.value} for "
                f"{value.comparison.value}/{value.window.value}"
            )
        if value.base_effect_treatment in {
            BaseEffectTreatment.PRESENT_UNADJUSTED,
            BaseEffectTreatment.UNKNOWN,
        }:
            reasons.append(f"base effect is {value.base_effect_treatment.value}")
        if value.one_off_treatment in {
            OneOffTreatment.INCLUDED_UNADJUSTED,
            OneOffTreatment.UNKNOWN,
        }:
            reasons.append(f"one-off treatment is {value.one_off_treatment.value}")
        if reasons:
            level = trend = acceleration = None
            status = FeatureCalculationStatus.UNAVAILABLE
        else:
            assert value.level is not None
            assert value.current_change is not None
            assert value.prior_change is not None
            level = value.level
            trend = value.current_change
            acceleration = value.current_change - value.prior_change
            status = FeatureCalculationStatus.QUANTIFIED
        return FundamentalImprovementComponentResult(
            metric=metric,
            status=status,
            level=level,
            trend=trend,
            acceleration=acceleration,
            level_unit=value.level_unit,
            change_unit=value.change_unit,
            currency=value.currency,
            comparison=value.comparison,
            window=value.window,
            seasonality_treatment=value.seasonality_treatment,
            base_effect_treatment=value.base_effect_treatment,
            one_off_treatment=value.one_off_treatment,
            provenance=value.provenance,
            unavailable_reasons=tuple(reasons),
        )


def fundamental_improvement_definition_v0() -> FundamentalImprovementDefinition:
    return FundamentalImprovementDefinition(
        factor_id="factor:fundamental-improvement:v0",
        formula_id="factor-formula:fundamental-improvement:level-trend-acceleration-breadth",
        formula_version="v0",
        missing_policy_version="unavailable-no-zero-fill:v1",
        winsorization_version="not-applied-company-level-raw:v1",
        standardization_version="not-applied-company-level-raw:v1",
        neutralization_version="exposures-carried-not-applied:v1",
        neutralization_exposure_names=("industry", "size", "beta"),
        required_metrics=tuple(FundamentalImprovementMetric),
        scientific_status=ImprovementScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "BaseEffectTreatment",
    "FundamentalImprovementDefinition",
    "FundamentalImprovementExposures",
    "FundamentalImprovementInput",
    "FundamentalImprovementMetric",
    "FundamentalImprovementResult",
    "ImprovementComparison",
    "ImprovementInputProvenance",
    "ImprovementResultStatus",
    "ImprovementScientificStatus",
    "ImprovementWindow",
    "OneOffTreatment",
    "SeasonalityTreatment",
    "fundamental_improvement_definition_v0",
]
