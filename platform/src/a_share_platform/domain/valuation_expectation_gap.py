"""Provider-neutral, scientifically unvalidated Valuation Expectation Gap V0.

The factor keeps relative valuation observations and expectation ranges
separate.  Its core output is an interval computed as fundamental anchor minus
market-implied expectation; it deliberately has no target-price field.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum

from .features import FeaturePeriod
from .industry_templates import IndustryTemplateId
from .metrics import MetricUnit
from .pit import DataTrustState
from .run_context import DataMode

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


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


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _unique_texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(values)
    if not result or any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{field_name} must contain non-empty text")
    if len(result) != len(set(result)):
        raise ValueError(f"{field_name} must be unique")
    return result


def _evidence_gate(
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
    decision_time: datetime | None,
    latest_source_available_at: datetime | None,
    label: str,
) -> tuple[DataMode, DataTrustState]:
    mode = DataMode(data_mode)
    trust = DataTrustState(trust_state)
    if trust is DataTrustState.RAW:
        raise ValueError(f"raw inputs cannot enter {label}")
    if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
        raise PermissionError(f"strict_historical {label} requires pit_verified inputs")
    clocks = (decision_time, latest_source_available_at)
    if any(value is None for value in clocks) and any(value is not None for value in clocks):
        raise ValueError("decision_time and latest_source_available_at must be present together")
    if decision_time is not None and latest_source_available_at is not None:
        decision = _aware(decision_time, "decision_time")
        available = _aware(latest_source_available_at, "latest_source_available_at")
        if available > decision:
            raise ValueError("available_at cannot exceed decision_time")
    elif mode is DataMode.STRICT_HISTORICAL:
        raise PermissionError(
            f"strict_historical {label} requires available_at <= decision_time evidence"
        )
    return mode, trust


class ValuationMetric(str, Enum):
    EARNINGS_TO_PRICE = "earnings_to_price"
    BOOK_TO_PRICE = "book_to_price"
    FREE_CASH_FLOW_YIELD = "free_cash_flow_yield"
    ENTERPRISE_VALUE_TO_EBIT = "enterprise_value_to_ebit"


class ValuationExpectationSource(str, Enum):
    MARKET_IMPLIED = "market_implied"
    FUNDAMENTAL_ANCHOR = "fundamental_anchor"


class ValuationExpectationMetric(str, Enum):
    GROWTH = "growth"
    MARGIN = "margin"
    RETURN_ON_EQUITY = "return_on_equity"
    RETURN_ON_INVESTED_CAPITAL = "return_on_invested_capital"


class ValuationComponentStatus(str, Enum):
    QUANTIFIED = "quantified"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"


class ValuationResultStatus(str, Enum):
    QUANTIFIED = "quantified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ValuationScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


class ValuationCoverageStatus(str, Enum):
    PARTIAL = "partial"


@dataclass(frozen=True)
class ValuationInputProvenance:
    dataset_version_id: str
    method_id: str
    method_version: str
    source_observation_ids: tuple[str, ...]
    content_hashes: tuple[str, ...]
    additional_dataset_version_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("dataset_version_id", "method_id", "method_version"):
            _text(getattr(self, name), name)
        observations = _unique_texts(
            self.source_observation_ids,
            "source_observation_ids",
        )
        hashes = tuple(self.content_hashes)
        if not hashes or any(
            not isinstance(value, str) or _SHA256.fullmatch(value) is None for value in hashes
        ):
            raise ValueError("content_hashes must contain sha256 hashes")
        if len(hashes) != len(set(hashes)):
            raise ValueError("content_hashes must be unique")
        object.__setattr__(self, "source_observation_ids", tuple(sorted(observations)))
        object.__setattr__(self, "content_hashes", tuple(sorted(hashes)))
        additional = tuple(sorted(self.additional_dataset_version_ids))
        if len(additional) != len(set(additional)) or any(
            not isinstance(value, str) or not value.strip() for value in additional
        ):
            raise ValueError("additional_dataset_version_ids must be unique non-empty text")
        if self.dataset_version_id in additional:
            raise ValueError("primary dataset_version_id cannot be repeated")
        object.__setattr__(self, "additional_dataset_version_ids", additional)

    @property
    def dataset_version_ids(self) -> tuple[str, ...]:
        return (self.dataset_version_id, *self.additional_dataset_version_ids)


@dataclass(frozen=True)
class _MetricSpec:
    numerator_unit: MetricUnit
    numerator_period: FeaturePeriod
    denominator_unit: MetricUnit
    denominator_period: FeaturePeriod


_METRIC_SPECS = {
    ValuationMetric.EARNINGS_TO_PRICE: _MetricSpec(
        MetricUnit.CURRENCY_PER_SHARE,
        FeaturePeriod.TTM,
        MetricUnit.CURRENCY_PER_SHARE,
        FeaturePeriod.INSTANT,
    ),
    ValuationMetric.BOOK_TO_PRICE: _MetricSpec(
        MetricUnit.CURRENCY_PER_SHARE,
        FeaturePeriod.INSTANT,
        MetricUnit.CURRENCY_PER_SHARE,
        FeaturePeriod.INSTANT,
    ),
    ValuationMetric.FREE_CASH_FLOW_YIELD: _MetricSpec(
        MetricUnit.CURRENCY_PER_SHARE,
        FeaturePeriod.TTM,
        MetricUnit.CURRENCY_PER_SHARE,
        FeaturePeriod.INSTANT,
    ),
    ValuationMetric.ENTERPRISE_VALUE_TO_EBIT: _MetricSpec(
        MetricUnit.CURRENCY,
        FeaturePeriod.INSTANT,
        MetricUnit.CURRENCY,
        FeaturePeriod.TTM,
    ),
}


@dataclass(frozen=True)
class ValuationMetricInput:
    metric: ValuationMetric
    numerator: Decimal | None
    denominator: Decimal | None
    numerator_unit: MetricUnit
    numerator_period: FeaturePeriod
    denominator_unit: MetricUnit
    denominator_period: FeaturePeriod
    currency: str
    provenance: ValuationInputProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    unavailable_reasons: tuple[str, ...] = ()
    decision_time: datetime | None = None
    latest_source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        metric = ValuationMetric(self.metric)
        object.__setattr__(self, "metric", metric)
        for name in ("numerator", "denominator"):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name)
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("numerator and denominator must be available together")
        specification = _METRIC_SPECS[metric]
        numerator_unit = MetricUnit(self.numerator_unit)
        denominator_unit = MetricUnit(self.denominator_unit)
        numerator_period = FeaturePeriod(self.numerator_period)
        denominator_period = FeaturePeriod(self.denominator_period)
        if numerator_unit is not specification.numerator_unit:
            raise ValueError(f"{metric.value} numerator unit is incompatible")
        if denominator_unit is not specification.denominator_unit:
            raise ValueError(f"{metric.value} denominator unit is incompatible")
        if numerator_period is not specification.numerator_period:
            raise ValueError(f"{metric.value} numerator period is incompatible")
        if denominator_period is not specification.denominator_period:
            raise ValueError(f"{metric.value} denominator period is incompatible")
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ValueError("valuation input currency must be a three-letter code")
        if not isinstance(self.provenance, ValuationInputProvenance):
            raise TypeError("provenance must be ValuationInputProvenance")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
            label="valuation metric",
        )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        reasons = tuple(self.unavailable_reasons)
        if self.numerator is None:
            if not reasons:
                raise ValueError("missing valuation metric requires unavailable_reasons")
            _unique_texts(reasons, "unavailable_reasons")
        elif reasons:
            raise ValueError("available valuation metric cannot carry unavailable_reasons")
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class ValuationExpectationRangeInput:
    source: ValuationExpectationSource
    expectation_metric: ValuationExpectationMetric
    lower: Decimal | None
    upper: Decimal | None
    unit: MetricUnit
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    provenance: ValuationInputProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    unavailable_reasons: tuple[str, ...] = ()
    decision_time: datetime | None = None
    latest_source_available_at: datetime | None = None

    def __post_init__(self) -> None:
        source = ValuationExpectationSource(self.source)
        metric = ValuationExpectationMetric(self.expectation_metric)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "expectation_metric", metric)
        if (self.lower is None) != (self.upper is None):
            raise ValueError("expectation interval bounds must be available together")
        if self.lower is not None and self.upper is not None:
            lower = _decimal(self.lower, "lower")
            upper = _decimal(self.upper, "upper")
            if upper < lower:
                raise ValueError("expectation interval upper cannot be below lower")
        unit = MetricUnit(self.unit)
        if unit is not MetricUnit.RATIO:
            raise ValueError("expectation interval unit must be ratio")
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "assumptions", _unique_texts(self.assumptions, "assumptions"))
        object.__setattr__(
            self,
            "invalidation_conditions",
            _unique_texts(self.invalidation_conditions, "invalidation_conditions"),
        )
        if not isinstance(self.provenance, ValuationInputProvenance):
            raise TypeError("provenance must be ValuationInputProvenance")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
            label="expectation range",
        )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        reasons = tuple(self.unavailable_reasons)
        if self.lower is None:
            if not reasons:
                raise ValueError("missing expectation range requires unavailable_reasons")
            _unique_texts(reasons, "unavailable_reasons")
        elif reasons:
            raise ValueError("available expectation range cannot carry unavailable_reasons")
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class ValuationExposures:
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
class ValuationComponentResult:
    metric: ValuationMetric
    status: ValuationComponentStatus
    value: Decimal | None
    unit: MetricUnit
    currency: str | None
    numerator_period: FeaturePeriod | None
    denominator_period: FeaturePeriod | None
    provenance: ValuationInputProvenance | None
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric", ValuationMetric(self.metric))
        status = ValuationComponentStatus(self.status)
        object.__setattr__(self, "status", status)
        if MetricUnit(self.unit) is not MetricUnit.RATIO:
            raise ValueError("valuation component output must be ratio")
        if status is ValuationComponentStatus.QUANTIFIED:
            if self.value is None or self.provenance is None:
                raise ValueError("quantified valuation component requires value and provenance")
            _decimal(self.value, "value")
            if self.unavailable_reasons:
                raise ValueError("quantified component cannot carry unavailable reasons")
        else:
            if self.value is not None:
                raise ValueError("unavailable component cannot carry a value")
            if not self.unavailable_reasons:
                raise ValueError("unavailable component requires reasons")


@dataclass(frozen=True)
class ValuationExpectationInterval:
    expectation_metric: ValuationExpectationMetric
    lower: Decimal
    upper: Decimal
    unit: MetricUnit

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "expectation_metric",
            ValuationExpectationMetric(self.expectation_metric),
        )
        lower = _decimal(self.lower, "lower")
        upper = _decimal(self.upper, "upper")
        if upper < lower:
            raise ValueError("interval upper cannot be below lower")
        if MetricUnit(self.unit) is not MetricUnit.RATIO:
            raise ValueError("expectation output unit must be ratio")


@dataclass(frozen=True)
class ValuationExpectationGapResult:
    status: ValuationResultStatus
    component_results: tuple[ValuationComponentResult, ...]
    market_implied_interval: ValuationExpectationInterval | None
    fundamental_anchor_interval: ValuationExpectationInterval | None
    gap_interval: ValuationExpectationInterval | None
    expectation_metric: ValuationExpectationMetric | None
    industry_template_id: IndustryTemplateId
    industry_template_version: str
    currency: str
    comparable_set_version_id: str
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]
    exposures: ValuationExposures
    data_mode: DataMode
    historical_eligible: bool
    decision_time: datetime | None
    latest_input_available_at: datetime | None
    formula_id: str
    formula_version: str
    definition_hash: str
    coverage_status: ValuationCoverageStatus
    coverage_gaps: tuple[str, ...]
    input_dataset_version_ids: tuple[str, ...]
    input_content_hashes: tuple[str, ...]
    warnings: tuple[str, ...]
    scientific_status: ValuationScientificStatus

    def component(self, metric: ValuationMetric) -> ValuationComponentResult:
        selected = [value for value in self.component_results if value.metric is metric]
        if len(selected) != 1:
            raise LookupError(f"valuation component is unavailable: {metric.value}")
        return selected[0]


@dataclass(frozen=True)
class ValuationExpectationGapDefinition:
    factor_id: str
    formula_id: str
    formula_version: str
    industry_template_id: IndustryTemplateId
    industry_template_version: str
    applicable_metrics: tuple[ValuationMetric, ...]
    not_applicable_metrics: tuple[ValuationMetric, ...]
    allowed_expectation_metrics: tuple[ValuationExpectationMetric, ...]
    industry_assumption: str
    coverage_status: ValuationCoverageStatus
    coverage_gaps: tuple[str, ...]
    scientific_status: ValuationScientificStatus
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "factor_id",
            "formula_id",
            "formula_version",
            "industry_template_version",
            "industry_assumption",
        ):
            _text(getattr(self, name), name)
        template = IndustryTemplateId(self.industry_template_id)
        applicable = tuple(ValuationMetric(value) for value in self.applicable_metrics)
        not_applicable = tuple(ValuationMetric(value) for value in self.not_applicable_metrics)
        if set(applicable).intersection(not_applicable):
            raise ValueError("valuation metric applicability sets must be disjoint")
        if set(applicable) | set(not_applicable) != set(ValuationMetric):
            raise ValueError("valuation applicability must classify every V0 metric")
        allowed = tuple(
            ValuationExpectationMetric(value) for value in self.allowed_expectation_metrics
        )
        if not allowed:
            raise ValueError("allowed_expectation_metrics must not be empty")
        gaps = _unique_texts(self.coverage_gaps, "coverage_gaps")
        coverage = ValuationCoverageStatus(self.coverage_status)
        scientific = ValuationScientificStatus(self.scientific_status)
        if scientific is not ValuationScientificStatus.NOT_EVALUATED:
            raise ValueError("Valuation V0 cannot claim scientific validation")
        object.__setattr__(self, "industry_template_id", template)
        object.__setattr__(self, "applicable_metrics", applicable)
        object.__setattr__(self, "not_applicable_metrics", not_applicable)
        object.__setattr__(self, "allowed_expectation_metrics", allowed)
        object.__setattr__(self, "coverage_status", coverage)
        object.__setattr__(self, "coverage_gaps", gaps)
        object.__setattr__(self, "scientific_status", scientific)
        payload = {
            "factor_id": self.factor_id,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "industry_template_id": template.value,
            "industry_template_version": self.industry_template_version,
            "applicable_metrics": [value.value for value in applicable],
            "not_applicable_metrics": [value.value for value in not_applicable],
            "allowed_expectation_metrics": [value.value for value in allowed],
            "industry_assumption": self.industry_assumption,
            "coverage_gaps": gaps,
            "scientific_status": scientific.value,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        object.__setattr__(
            self,
            "definition_hash",
            f"sha256:{hashlib.sha256(encoded).hexdigest()}",
        )

    def calculate(
        self,
        values: Mapping[ValuationMetric, ValuationMetricInput],
        *,
        market_implied: ValuationExpectationRangeInput,
        fundamental_anchor: ValuationExpectationRangeInput,
        exposures: ValuationExposures,
        data_mode: DataMode,
        currency: str,
        comparable_set_version_id: str,
    ) -> ValuationExpectationGapResult:
        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        if not isinstance(exposures, ValuationExposures):
            raise TypeError("exposures must be ValuationExposures")
        if not isinstance(market_implied, ValuationExpectationRangeInput) or not isinstance(
            fundamental_anchor,
            ValuationExpectationRangeInput,
        ):
            raise TypeError("expectation inputs must be ValuationExpectationRangeInput")
        if not isinstance(currency, str) or re.fullmatch(r"[A-Z]{3}", currency) is None:
            raise ValueError("result currency must be a three-letter code")
        _text(comparable_set_version_id, "comparable_set_version_id")
        mode = DataMode(data_mode)
        normalized: dict[ValuationMetric, ValuationMetricInput] = {}
        for raw_metric, value in values.items():
            metric = ValuationMetric(raw_metric)
            if metric in normalized:
                raise ValueError(f"duplicate valuation input: {metric.value}")
            if metric not in self.applicable_metrics:
                raise ValueError(f"valuation metric is not applicable: {metric.value}")
            if not isinstance(value, ValuationMetricInput):
                raise TypeError(f"valuation input {metric.value} has invalid type")
            if value.metric is not metric:
                raise ValueError(f"valuation input metric mismatch: {metric.value}")
            self._require_mode(value.data_mode, value.trust_state, mode)
            if value.currency != currency:
                raise ValueError("valuation input currency does not match result currency")
            normalized[metric] = value
        self._validate_expectation(
            market_implied,
            expected_source=ValuationExpectationSource.MARKET_IMPLIED,
            mode=mode,
        )
        self._validate_expectation(
            fundamental_anchor,
            expected_source=ValuationExpectationSource.FUNDAMENTAL_ANCHOR,
            mode=mode,
        )
        if market_implied.expectation_metric is not fundamental_anchor.expectation_metric:
            raise ValueError("market-implied and anchor expectation metrics must match")
        if market_implied.expectation_metric not in self.allowed_expectation_metrics:
            raise ValueError("expectation metric is not applicable to industry template")

        components = tuple(
            self._component(metric, normalized.get(metric))
            if metric in self.applicable_metrics
            else self._not_applicable_component(metric)
            for metric in ValuationMetric
        )
        expectation_missing = market_implied.lower is None or fundamental_anchor.lower is None
        if expectation_missing:
            market_interval = self._interval_or_none(market_implied)
            anchor_interval = self._interval_or_none(fundamental_anchor)
            gap_interval = None
            status = ValuationResultStatus.UNAVAILABLE
            unavailable_reasons = tuple(
                dict.fromkeys(
                    (
                        *market_implied.unavailable_reasons,
                        *fundamental_anchor.unavailable_reasons,
                    )
                )
            )
        else:
            market_interval = self._interval_or_none(market_implied)
            anchor_interval = self._interval_or_none(fundamental_anchor)
            assert market_interval is not None
            assert anchor_interval is not None
            gap_interval = ValuationExpectationInterval(
                expectation_metric=market_implied.expectation_metric,
                lower=anchor_interval.lower - market_interval.upper,
                upper=anchor_interval.upper - market_interval.lower,
                unit=MetricUnit.RATIO,
            )
            status = (
                ValuationResultStatus.PARTIAL
                if any(value.status is ValuationComponentStatus.UNAVAILABLE for value in components)
                else ValuationResultStatus.QUANTIFIED
            )
            unavailable_reasons = ()

        evidence: tuple[
            ValuationMetricInput | ValuationExpectationRangeInput,
            ...,
        ] = (*normalized.values(), market_implied, fundamental_anchor)
        if mode is DataMode.STRICT_HISTORICAL:
            decision_times = {value.decision_time for value in evidence}
            if len(decision_times) != 1:
                raise ValueError("strict_historical valuation inputs must share decision_time")
            decision_time = next(iter(decision_times))
            assert decision_time is not None
            available_times = tuple(value.latest_source_available_at for value in evidence)
            assert all(value is not None for value in available_times)
            latest_available = max(value for value in available_times if value is not None)
        else:
            decision_time = None
            latest_available = None
        warnings: list[str] = []
        if mode is DataMode.CURRENT_RESEARCH:
            warnings.append(
                "current_research valuation is current-only and not strict historical evidence"
            )
        if status is ValuationResultStatus.PARTIAL:
            warnings.append(
                "partial valuation excludes unavailable applicable metrics without zero filling"
            )
        provenances = tuple(value.provenance for value in evidence)
        return ValuationExpectationGapResult(
            status=status,
            component_results=components,
            market_implied_interval=market_interval,
            fundamental_anchor_interval=anchor_interval,
            gap_interval=gap_interval,
            expectation_metric=market_implied.expectation_metric,
            industry_template_id=self.industry_template_id,
            industry_template_version=self.industry_template_version,
            currency=currency,
            comparable_set_version_id=comparable_set_version_id,
            assumptions=tuple(
                dict.fromkeys(
                    (
                        self.industry_assumption,
                        *market_implied.assumptions,
                        *fundamental_anchor.assumptions,
                    )
                )
            ),
            invalidation_conditions=tuple(
                dict.fromkeys(
                    (
                        *market_implied.invalidation_conditions,
                        *fundamental_anchor.invalidation_conditions,
                    )
                )
            ),
            unavailable_reasons=unavailable_reasons,
            exposures=exposures,
            data_mode=mode,
            historical_eligible=mode is DataMode.STRICT_HISTORICAL,
            decision_time=decision_time,
            latest_input_available_at=latest_available,
            formula_id=self.formula_id,
            formula_version=self.formula_version,
            definition_hash=self.definition_hash,
            coverage_status=self.coverage_status,
            coverage_gaps=self.coverage_gaps,
            input_dataset_version_ids=tuple(
                sorted(
                    {
                        dataset_id
                        for value in provenances
                        for dataset_id in value.dataset_version_ids
                    }
                )
            ),
            input_content_hashes=tuple(
                sorted({item for value in provenances for item in value.content_hashes})
            ),
            warnings=tuple(warnings),
            scientific_status=self.scientific_status,
        )

    @staticmethod
    def _require_mode(
        input_mode: DataMode,
        trust_state: DataTrustState,
        requested_mode: DataMode,
    ) -> None:
        if input_mode is not requested_mode:
            raise PermissionError(
                "current_research inputs cannot be relabelled as strict historical results"
            )
        if (
            requested_mode is DataMode.STRICT_HISTORICAL
            and trust_state is not DataTrustState.PIT_VERIFIED
        ):
            raise PermissionError("strict_historical valuation requires pit_verified inputs")

    def _validate_expectation(
        self,
        value: ValuationExpectationRangeInput,
        *,
        expected_source: ValuationExpectationSource,
        mode: DataMode,
    ) -> None:
        if value.source is not expected_source:
            raise ValueError(f"expected {expected_source.value} expectation source")
        self._require_mode(value.data_mode, value.trust_state, mode)

    @staticmethod
    def _interval_or_none(
        value: ValuationExpectationRangeInput,
    ) -> ValuationExpectationInterval | None:
        if value.lower is None or value.upper is None:
            return None
        return ValuationExpectationInterval(
            expectation_metric=value.expectation_metric,
            lower=value.lower,
            upper=value.upper,
            unit=value.unit,
        )

    @staticmethod
    def _component(
        metric: ValuationMetric,
        value: ValuationMetricInput | None,
    ) -> ValuationComponentResult:
        specification = _METRIC_SPECS[metric]
        if value is None:
            return ValuationComponentResult(
                metric=metric,
                status=ValuationComponentStatus.UNAVAILABLE,
                value=None,
                unit=MetricUnit.RATIO,
                currency=None,
                numerator_period=specification.numerator_period,
                denominator_period=specification.denominator_period,
                provenance=None,
                unavailable_reasons=("required valuation metric input is missing",),
            )
        if value.numerator is None or value.denominator is None:
            return ValuationComponentResult(
                metric=metric,
                status=ValuationComponentStatus.UNAVAILABLE,
                value=None,
                unit=MetricUnit.RATIO,
                currency=None,
                numerator_period=value.numerator_period,
                denominator_period=value.denominator_period,
                provenance=value.provenance,
                unavailable_reasons=value.unavailable_reasons,
            )
        invalid = value.denominator <= 0 or (
            metric is ValuationMetric.ENTERPRISE_VALUE_TO_EBIT and value.numerator <= 0
        )
        if invalid:
            return ValuationComponentResult(
                metric=metric,
                status=ValuationComponentStatus.UNAVAILABLE,
                value=None,
                unit=MetricUnit.RATIO,
                currency=None,
                numerator_period=value.numerator_period,
                denominator_period=value.denominator_period,
                provenance=value.provenance,
                unavailable_reasons=(
                    "valuation ratio is invalid for non-positive denominator or enterprise value",
                ),
            )
        return ValuationComponentResult(
            metric=metric,
            status=ValuationComponentStatus.QUANTIFIED,
            value=value.numerator / value.denominator,
            unit=MetricUnit.RATIO,
            currency=None,
            numerator_period=value.numerator_period,
            denominator_period=value.denominator_period,
            provenance=value.provenance,
            unavailable_reasons=(),
        )

    def _not_applicable_component(
        self,
        metric: ValuationMetric,
    ) -> ValuationComponentResult:
        return ValuationComponentResult(
            metric=metric,
            status=ValuationComponentStatus.NOT_APPLICABLE,
            value=None,
            unit=MetricUnit.RATIO,
            currency=None,
            numerator_period=None,
            denominator_period=None,
            provenance=None,
            unavailable_reasons=(
                f"{metric.value} is not applicable to {self.industry_template_id.value}",
            ),
        )


def valuation_expectation_gap_definition_v0(
    template_id: IndustryTemplateId,
) -> ValuationExpectationGapDefinition:
    template = IndustryTemplateId(template_id)
    all_metrics = tuple(ValuationMetric)
    applicable: tuple[ValuationMetric, ...]
    allowed_expectations: tuple[ValuationExpectationMetric, ...]
    if template is IndustryTemplateId.BANK:
        applicable = (
            ValuationMetric.EARNINGS_TO_PRICE,
            ValuationMetric.BOOK_TO_PRICE,
        )
        allowed_expectations = (ValuationExpectationMetric.RETURN_ON_EQUITY,)
        assumption = "Bank valuation uses E/P and B/P; FCF yield and EV/EBIT are not comparable."
    else:
        applicable = all_metrics
        allowed_expectations = (
            ValuationExpectationMetric.GROWTH,
            ValuationExpectationMetric.MARGIN,
            ValuationExpectationMetric.RETURN_ON_INVESTED_CAPITAL,
        )
        assumption = (
            "Non-financial valuation uses E/P, B/P, FCF yield, and EV/EBIT with "
            "industry-versioned comparables."
        )
    return ValuationExpectationGapDefinition(
        factor_id=f"factor:valuation-expectation-gap:{template.value}:v0",
        formula_id="factor-formula:fundamental-anchor-minus-market-implied-interval",
        formula_version="v0",
        industry_template_id=template,
        industry_template_version="v0",
        applicable_metrics=applicable,
        not_applicable_metrics=tuple(metric for metric in all_metrics if metric not in applicable),
        allowed_expectation_metrics=allowed_expectations,
        industry_assumption=assumption,
        coverage_status=ValuationCoverageStatus.PARTIAL,
        coverage_gaps=(
            "historical_peer_distribution_execution",
            "analyst_consensus_and_revision_when_available",
            "scenario_sensitivity_execution",
        ),
        scientific_status=ValuationScientificStatus.NOT_EVALUATED,
    )


__all__ = [
    "ValuationComponentStatus",
    "ValuationCoverageStatus",
    "ValuationExpectationGapDefinition",
    "ValuationExpectationGapResult",
    "ValuationExpectationInterval",
    "ValuationExpectationMetric",
    "ValuationExpectationRangeInput",
    "ValuationExpectationSource",
    "ValuationExposures",
    "ValuationInputProvenance",
    "ValuationMetric",
    "ValuationMetricInput",
    "ValuationResultStatus",
    "ValuationScientificStatus",
    "valuation_expectation_gap_definition_v0",
]
