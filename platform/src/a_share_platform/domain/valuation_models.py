"""Provider-neutral engineering models for P5 valuation analysis.

The models in this module expose explicit intervals and unavailable states.
They are deterministic engineering baselines, not scientifically validated
forecast models, and they deliberately do not expose a point target price.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .industry_templates import IndustryTemplateId
from .metrics import MetricUnit
from .pit import DataTrustState
from .provider import (
    DataField,
    LicenseStatus,
    ProviderFieldPolicy,
    ProviderUse,
)
from .run_context import DataMode
from .valuation_expectation_gap import (
    ValuationComponentResult,
    ValuationComponentStatus,
    ValuationExpectationMetric,
    ValuationInputProvenance,
    ValuationMetric,
)


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


def _unique_reasons(values: tuple[str, ...]) -> tuple[str, ...]:
    reasons = tuple(values)
    if len(reasons) != len(set(reasons)) or any(
        not isinstance(reason, str) or not reason.strip() for reason in reasons
    ):
        raise ValueError("unavailable_reasons must contain unique non-empty text")
    return reasons


def _evidence_gate(
    *,
    data_mode: DataMode,
    trust_state: DataTrustState,
    decision_time: datetime,
    latest_source_available_at: datetime,
    label: str,
) -> tuple[DataMode, DataTrustState]:
    mode = DataMode(data_mode)
    trust = DataTrustState(trust_state)
    decision = _aware(decision_time, "decision_time")
    available = _aware(latest_source_available_at, "latest_source_available_at")
    if available > decision:
        raise ValueError("available_at cannot exceed decision_time")
    if trust is DataTrustState.RAW:
        raise ValueError(f"raw inputs cannot enter {label}")
    if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
        raise PermissionError(f"strict_historical {label} requires pit_verified inputs")
    return mode, trust


def _validate_interval(lower: Decimal, upper: Decimal, label: str) -> None:
    _decimal(lower, f"{label}_lower")
    _decimal(upper, f"{label}_upper")
    if upper < lower:
        raise ValueError(f"{label} upper cannot be below lower")


def _merge_provenance(
    values: tuple[ValuationInputProvenance, ...],
    *,
    method_id: str,
) -> ValuationInputProvenance:
    datasets = tuple(
        sorted({dataset_id for value in values for dataset_id in value.dataset_version_ids})
    )
    return ValuationInputProvenance(
        dataset_version_id=datasets[0],
        additional_dataset_version_ids=datasets[1:],
        method_id=method_id,
        method_version="v0",
        source_observation_ids=tuple(
            sorted(
                {
                    observation_id
                    for value in values
                    for observation_id in value.source_observation_ids
                }
            )
        ),
        content_hashes=tuple(
            sorted({content_hash for value in values for content_hash in value.content_hashes})
        ),
    )


def _method_lineage(values: tuple[ValuationInputProvenance, ...]) -> tuple[str, ...]:
    return tuple(sorted({f"{value.method_id}@{value.method_version}" for value in values}))


class RelativeReferenceKind(str, Enum):
    HISTORICAL = "historical"
    INDUSTRY = "industry"
    PEER = "peer"


class FundamentalAnchorMethod(str, Enum):
    FCF_GROWING_PERPETUITY = "fcf_growing_perpetuity"
    BANK_JUSTIFIED_PRICE_TO_BOOK = "bank_justified_price_to_book"


class ValuationModelStatus(str, Enum):
    QUANTIFIED = "quantified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ValuationModelScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class IndustryValuationPolicy:
    industry_template_id: IndustryTemplateId
    anchor_method: FundamentalAnchorMethod
    expectation_metric: ValuationExpectationMetric
    relative_metrics: tuple[ValuationMetric, ...]
    policy_version: str

    def __post_init__(self) -> None:
        template = IndustryTemplateId(self.industry_template_id)
        method = FundamentalAnchorMethod(self.anchor_method)
        expectation = ValuationExpectationMetric(self.expectation_metric)
        metrics = tuple(ValuationMetric(metric) for metric in self.relative_metrics)
        if not metrics or len(metrics) != len(set(metrics)):
            raise ValueError("relative_metrics must be non-empty and unique")
        if template is IndustryTemplateId.BANK:
            if method is not FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK:
                raise ValueError("bank industry template requires justified price-to-book")
            if expectation is not ValuationExpectationMetric.RETURN_ON_EQUITY:
                raise ValueError("bank industry template requires return-on-equity expectation")
        elif method is not FundamentalAnchorMethod.FCF_GROWING_PERPETUITY:
            raise ValueError("non-financial industry template requires FCF anchor")
        _text(self.policy_version, "policy_version")
        object.__setattr__(self, "industry_template_id", template)
        object.__setattr__(self, "anchor_method", method)
        object.__setattr__(self, "expectation_metric", expectation)
        object.__setattr__(self, "relative_metrics", metrics)


def industry_valuation_policy_v0(
    template_id: IndustryTemplateId,
) -> IndustryValuationPolicy:
    template = IndustryTemplateId(template_id)
    if template is IndustryTemplateId.BANK:
        return IndustryValuationPolicy(
            industry_template_id=template,
            anchor_method=FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK,
            expectation_metric=ValuationExpectationMetric.RETURN_ON_EQUITY,
            relative_metrics=(
                ValuationMetric.EARNINGS_TO_PRICE,
                ValuationMetric.BOOK_TO_PRICE,
            ),
            policy_version="industry-valuation-policy:v0",
        )
    return IndustryValuationPolicy(
        industry_template_id=template,
        anchor_method=FundamentalAnchorMethod.FCF_GROWING_PERPETUITY,
        expectation_metric=ValuationExpectationMetric.GROWTH,
        relative_metrics=tuple(ValuationMetric),
        policy_version="industry-valuation-policy:v0",
    )


@dataclass(frozen=True)
class RelativeValuationReferenceInput:
    metric: ValuationMetric
    reference_kind: RelativeReferenceKind
    median_value: Decimal | None
    observation_count: int
    unit: MetricUnit
    comparable_set_version_id: str
    provenance: ValuationInputProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    latest_source_available_at: datetime
    unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        metric = ValuationMetric(self.metric)
        kind = RelativeReferenceKind(self.reference_kind)
        if MetricUnit(self.unit) is not MetricUnit.RATIO:
            raise ValueError("relative valuation reference unit must be ratio")
        if not isinstance(self.observation_count, int) or isinstance(self.observation_count, bool):
            raise TypeError("observation_count must be an integer")
        if self.observation_count < 0:
            raise ValueError("observation_count cannot be negative")
        _text(self.comparable_set_version_id, "comparable_set_version_id")
        if not isinstance(self.provenance, ValuationInputProvenance):
            raise TypeError("provenance must be ValuationInputProvenance")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
            label="relative valuation reference",
        )
        reasons = _unique_reasons(self.unavailable_reasons)
        if self.median_value is None:
            if self.observation_count != 0 or not reasons:
                raise ValueError(
                    "missing relative reference requires zero observations and reasons"
                )
        else:
            _decimal(self.median_value, "median_value")
            if self.median_value <= 0:
                raise ValueError("relative reference median must be positive")
            if self.observation_count <= 0:
                raise ValueError("available relative reference requires observations")
            if reasons:
                raise ValueError("available relative reference cannot carry reasons")
        object.__setattr__(self, "metric", metric)
        object.__setattr__(self, "reference_kind", kind)
        object.__setattr__(self, "unit", MetricUnit.RATIO)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class RelativeValuationComparison:
    reference_kind: RelativeReferenceKind
    status: ValuationModelStatus
    subject_value: Decimal | None
    reference_median: Decimal | None
    relative_gap: Decimal | None
    unit: MetricUnit
    observation_count: int
    provenance: ValuationInputProvenance | None
    unavailable_reasons: tuple[str, ...]


@dataclass(frozen=True)
class RelativeValuationResult:
    metric: ValuationMetric
    status: ValuationModelStatus
    comparisons: tuple[RelativeValuationComparison, ...]
    comparable_set_version_id: str | None
    model_version: str
    scientific_status: ValuationModelScientificStatus

    def comparison(self, kind: RelativeReferenceKind) -> RelativeValuationComparison:
        normalized = RelativeReferenceKind(kind)
        matches = [value for value in self.comparisons if value.reference_kind is normalized]
        if len(matches) != 1:
            raise LookupError(f"relative valuation comparison is unavailable: {normalized.value}")
        return matches[0]


@dataclass(frozen=True)
class RelativeValuationModelV0:
    model_version: str = "relative-valuation-model:v0"

    def calculate(
        self,
        subject: ValuationComponentResult,
        references: tuple[RelativeValuationReferenceInput, ...],
    ) -> RelativeValuationResult:
        if not isinstance(subject, ValuationComponentResult):
            raise TypeError("subject must be ValuationComponentResult")
        values = tuple(references)
        seen: set[RelativeReferenceKind] = set()
        comparable_ids: set[str] = set()
        evidence_modes: set[tuple[DataMode, DataTrustState]] = set()
        decision_times: set[datetime] = set()
        comparisons: list[RelativeValuationComparison] = []
        for value in values:
            if not isinstance(value, RelativeValuationReferenceInput):
                raise TypeError("references must contain RelativeValuationReferenceInput")
            if value.reference_kind in seen:
                raise ValueError(f"duplicate relative reference: {value.reference_kind.value}")
            if value.metric is not subject.metric:
                raise ValueError("relative reference metric does not match subject")
            seen.add(value.reference_kind)
            comparable_ids.add(value.comparable_set_version_id)
            evidence_modes.add((value.data_mode, value.trust_state))
            decision_times.add(value.decision_time)
            if (
                subject.status is not ValuationComponentStatus.QUANTIFIED
                or subject.value is None
                or subject.value <= 0
            ):
                comparisons.append(
                    RelativeValuationComparison(
                        reference_kind=value.reference_kind,
                        status=ValuationModelStatus.UNAVAILABLE,
                        subject_value=None,
                        reference_median=value.median_value,
                        relative_gap=None,
                        unit=MetricUnit.RATIO,
                        observation_count=value.observation_count,
                        provenance=value.provenance,
                        unavailable_reasons=("subject valuation component is unavailable",),
                    )
                )
            elif value.median_value is None:
                comparisons.append(
                    RelativeValuationComparison(
                        reference_kind=value.reference_kind,
                        status=ValuationModelStatus.UNAVAILABLE,
                        subject_value=subject.value,
                        reference_median=None,
                        relative_gap=None,
                        unit=MetricUnit.RATIO,
                        observation_count=0,
                        provenance=value.provenance,
                        unavailable_reasons=value.unavailable_reasons,
                    )
                )
            else:
                gap = (
                    value.median_value / subject.value - Decimal(1)
                    if subject.metric is ValuationMetric.ENTERPRISE_VALUE_TO_EBIT
                    else subject.value / value.median_value - Decimal(1)
                )
                comparisons.append(
                    RelativeValuationComparison(
                        reference_kind=value.reference_kind,
                        status=ValuationModelStatus.QUANTIFIED,
                        subject_value=subject.value,
                        reference_median=value.median_value,
                        relative_gap=gap,
                        unit=MetricUnit.RATIO,
                        observation_count=value.observation_count,
                        provenance=value.provenance,
                        unavailable_reasons=(),
                    )
                )
        if len(comparable_ids) > 1:
            raise ValueError("relative references must share one comparable_set_version_id")
        if seen != set(RelativeReferenceKind):
            raise ValueError(
                "historical, industry, and peer references each require a value or reason"
            )
        if len(evidence_modes) > 1:
            raise PermissionError("relative references must share one mode/trust contract")
        if len(decision_times) > 1:
            raise ValueError("relative references must share one decision_time")
        quantified = sum(value.status is ValuationModelStatus.QUANTIFIED for value in comparisons)
        if quantified == len(RelativeReferenceKind):
            status = ValuationModelStatus.QUANTIFIED
        elif quantified:
            status = ValuationModelStatus.PARTIAL
        else:
            status = ValuationModelStatus.UNAVAILABLE
        return RelativeValuationResult(
            metric=subject.metric,
            status=status,
            comparisons=tuple(comparisons),
            comparable_set_version_id=next(iter(comparable_ids), None),
            model_version=self.model_version,
            scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
        )


def relative_valuation_model_v0() -> RelativeValuationModelV0:
    return RelativeValuationModelV0()


@dataclass(frozen=True)
class FundamentalAnchorInput:
    method: FundamentalAnchorMethod
    industry_template_id: IndustryTemplateId
    current_price: Decimal
    base_value_per_share_lower: Decimal
    base_value_per_share_upper: Decimal
    profitability_lower: Decimal | None
    profitability_upper: Decimal | None
    discount_rate_lower: Decimal
    discount_rate_upper: Decimal
    perpetual_growth_lower: Decimal
    perpetual_growth_upper: Decimal
    current_price_unit: MetricUnit
    base_value_per_share_unit: MetricUnit
    rate_unit: MetricUnit
    currency: str
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    price_provenance: ValuationInputProvenance
    fundamental_provenance: ValuationInputProvenance
    assumption_provenance: ValuationInputProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    latest_source_available_at: datetime

    def __post_init__(self) -> None:
        method = FundamentalAnchorMethod(self.method)
        template = IndustryTemplateId(self.industry_template_id)
        policy = industry_valuation_policy_v0(template)
        if method is not policy.anchor_method:
            raise ValueError("anchor method is incompatible with industry template")
        for name in (
            "current_price",
            "base_value_per_share_lower",
            "base_value_per_share_upper",
            "discount_rate_lower",
            "discount_rate_upper",
            "perpetual_growth_lower",
            "perpetual_growth_upper",
        ):
            _decimal(getattr(self, name), name)
        if self.current_price <= 0:
            raise ValueError("current_price must be positive")
        _validate_interval(
            self.base_value_per_share_lower,
            self.base_value_per_share_upper,
            "base value per share",
        )
        if self.base_value_per_share_lower <= 0:
            raise ValueError("base value per share must be positive")
        _validate_interval(
            self.discount_rate_lower,
            self.discount_rate_upper,
            "discount rate",
        )
        _validate_interval(
            self.perpetual_growth_lower,
            self.perpetual_growth_upper,
            "perpetual growth",
        )
        if self.discount_rate_lower <= self.perpetual_growth_upper:
            raise ValueError("discount rate must exceed perpetual growth")
        if method is FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK:
            if self.profitability_lower is None or self.profitability_upper is None:
                raise ValueError("bank anchor requires profitability interval")
            _validate_interval(
                self.profitability_lower,
                self.profitability_upper,
                "profitability",
            )
            if self.profitability_lower <= self.perpetual_growth_upper:
                raise ValueError("bank profitability must exceed perpetual growth")
        elif self.profitability_lower is not None or self.profitability_upper is not None:
            raise ValueError("non-financial FCF anchor cannot carry profitability interval")
        if MetricUnit(self.current_price_unit) is not MetricUnit.CURRENCY_PER_SHARE:
            raise ValueError("current_price_unit must be currency_per_share")
        if MetricUnit(self.base_value_per_share_unit) is not MetricUnit.CURRENCY_PER_SHARE:
            raise ValueError("base_value_per_share_unit must be currency_per_share")
        if MetricUnit(self.rate_unit) is not MetricUnit.RATIO:
            raise ValueError("anchor rate_unit must be ratio")
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ValueError("currency must be a three-letter code")
        if not self.assumptions or any(not value.strip() for value in self.assumptions):
            raise ValueError("assumptions must contain non-empty text")
        if not self.invalidation_conditions or any(
            not value.strip() for value in self.invalidation_conditions
        ):
            raise ValueError("invalidation_conditions must contain non-empty text")
        for name in (
            "price_provenance",
            "fundamental_provenance",
            "assumption_provenance",
        ):
            if not isinstance(getattr(self, name), ValuationInputProvenance):
                raise TypeError(f"{name} must be ValuationInputProvenance")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
            label="fundamental anchor",
        )
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "industry_template_id", template)
        object.__setattr__(self, "current_price_unit", MetricUnit.CURRENCY_PER_SHARE)
        object.__setattr__(
            self,
            "base_value_per_share_unit",
            MetricUnit.CURRENCY_PER_SHARE,
        )
        object.__setattr__(self, "rate_unit", MetricUnit.RATIO)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)

    @property
    def provenances(self) -> tuple[ValuationInputProvenance, ...]:
        return (
            self.price_provenance,
            self.fundamental_provenance,
            self.assumption_provenance,
        )


@dataclass(frozen=True)
class UnavailableFundamentalAnchorInput:
    method: FundamentalAnchorMethod
    industry_template_id: IndustryTemplateId
    currency: str
    current_price_unit: MetricUnit
    base_value_per_share_unit: MetricUnit
    rate_unit: MetricUnit
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    provenances: tuple[ValuationInputProvenance, ...]
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    latest_source_available_at: datetime
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        method = FundamentalAnchorMethod(self.method)
        template = IndustryTemplateId(self.industry_template_id)
        if method is not industry_valuation_policy_v0(template).anchor_method:
            raise ValueError("anchor method is incompatible with industry template")
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ValueError("currency must be a three-letter code")
        if MetricUnit(self.current_price_unit) is not MetricUnit.CURRENCY_PER_SHARE:
            raise ValueError("current_price_unit must be currency_per_share")
        if MetricUnit(self.base_value_per_share_unit) is not MetricUnit.CURRENCY_PER_SHARE:
            raise ValueError("base_value_per_share_unit must be currency_per_share")
        if MetricUnit(self.rate_unit) is not MetricUnit.RATIO:
            raise ValueError("anchor rate_unit must be ratio")
        if not self.assumptions or any(not value.strip() for value in self.assumptions):
            raise ValueError("assumptions must contain non-empty text")
        if not self.invalidation_conditions or any(
            not value.strip() for value in self.invalidation_conditions
        ):
            raise ValueError("invalidation_conditions must contain non-empty text")
        provenances = tuple(self.provenances)
        if not provenances or any(
            not isinstance(value, ValuationInputProvenance) for value in provenances
        ):
            raise ValueError("unavailable anchor requires available provenance evidence")
        reasons = _unique_reasons(self.unavailable_reasons)
        if not reasons:
            raise ValueError("unavailable anchor requires unavailable_reasons")
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
            label="fundamental anchor",
        )
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "industry_template_id", template)
        object.__setattr__(self, "current_price_unit", MetricUnit.CURRENCY_PER_SHARE)
        object.__setattr__(
            self,
            "base_value_per_share_unit",
            MetricUnit.CURRENCY_PER_SHARE,
        )
        object.__setattr__(self, "rate_unit", MetricUnit.RATIO)
        object.__setattr__(self, "provenances", provenances)
        object.__setattr__(self, "unavailable_reasons", reasons)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)


@dataclass(frozen=True)
class FundamentalAnchorResult:
    status: ValuationModelStatus
    method: FundamentalAnchorMethod
    expectation_metric: ValuationExpectationMetric
    fundamental_expectation_lower: Decimal | None
    fundamental_expectation_upper: Decimal | None
    fair_value_lower: Decimal | None
    fair_value_upper: Decimal | None
    expected_return_lower: Decimal | None
    expected_return_upper: Decimal | None
    currency: str
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    provenance: ValuationInputProvenance
    input_method_versions: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]
    model_version: str
    scientific_status: ValuationModelScientificStatus


@dataclass(frozen=True)
class FundamentalAnchorModelV0:
    model_version: str = "fundamental-anchor-model:v0"

    def calculate(
        self,
        value: FundamentalAnchorInput | UnavailableFundamentalAnchorInput,
    ) -> FundamentalAnchorResult:
        if not isinstance(
            value,
            (FundamentalAnchorInput, UnavailableFundamentalAnchorInput),
        ):
            raise TypeError("value must be a fundamental anchor input")
        provenance = _merge_provenance(
            value.provenances,
            method_id=self.model_version,
        )
        input_method_versions = _method_lineage(value.provenances)
        if isinstance(value, UnavailableFundamentalAnchorInput):
            return FundamentalAnchorResult(
                status=ValuationModelStatus.UNAVAILABLE,
                method=value.method,
                expectation_metric=industry_valuation_policy_v0(
                    value.industry_template_id
                ).expectation_metric,
                fundamental_expectation_lower=None,
                fundamental_expectation_upper=None,
                fair_value_lower=None,
                fair_value_upper=None,
                expected_return_lower=None,
                expected_return_upper=None,
                currency=value.currency,
                assumptions=value.assumptions,
                invalidation_conditions=value.invalidation_conditions,
                provenance=provenance,
                input_method_versions=input_method_versions,
                unavailable_reasons=value.unavailable_reasons,
                model_version=self.model_version,
                scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
            )
        if value.method is FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK:
            assert value.profitability_lower is not None
            assert value.profitability_upper is not None
            candidates = tuple(
                book * (profitability - growth) / (discount - growth)
                for book in (
                    value.base_value_per_share_lower,
                    value.base_value_per_share_upper,
                )
                for profitability in (
                    value.profitability_lower,
                    value.profitability_upper,
                )
                for discount in (
                    value.discount_rate_lower,
                    value.discount_rate_upper,
                )
                for growth in (
                    value.perpetual_growth_lower,
                    value.perpetual_growth_upper,
                )
            )
            lower = min(candidates)
            upper = max(candidates)
            expectation_lower = value.profitability_lower
            expectation_upper = value.profitability_upper
        else:
            lower = (
                value.base_value_per_share_lower
                * (Decimal(1) + value.perpetual_growth_lower)
                / (value.discount_rate_upper - value.perpetual_growth_lower)
            )
            upper = (
                value.base_value_per_share_upper
                * (Decimal(1) + value.perpetual_growth_upper)
                / (value.discount_rate_lower - value.perpetual_growth_upper)
            )
            expectation_lower = value.perpetual_growth_lower
            expectation_upper = value.perpetual_growth_upper
        if lower < 0 or upper < lower:
            raise ValueError("anchor assumptions produce an invalid fair-value interval")
        return FundamentalAnchorResult(
            status=ValuationModelStatus.QUANTIFIED,
            method=value.method,
            expectation_metric=industry_valuation_policy_v0(
                value.industry_template_id
            ).expectation_metric,
            fundamental_expectation_lower=expectation_lower,
            fundamental_expectation_upper=expectation_upper,
            fair_value_lower=lower,
            fair_value_upper=upper,
            expected_return_lower=lower / value.current_price - Decimal(1),
            expected_return_upper=upper / value.current_price - Decimal(1),
            currency=value.currency,
            assumptions=value.assumptions,
            invalidation_conditions=value.invalidation_conditions,
            provenance=provenance,
            input_method_versions=input_method_versions,
            unavailable_reasons=(),
            model_version=self.model_version,
            scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
        )


def fundamental_anchor_model_v0() -> FundamentalAnchorModelV0:
    return FundamentalAnchorModelV0()


@dataclass(frozen=True)
class ImpliedExpectationResult:
    status: ValuationModelStatus
    expectation_metric: ValuationExpectationMetric
    lower: Decimal | None
    upper: Decimal | None
    unit: MetricUnit
    assumptions: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    provenance: ValuationInputProvenance
    input_method_versions: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]
    model_version: str
    scientific_status: ValuationModelScientificStatus


@dataclass(frozen=True)
class ImpliedExpectationModelV0:
    model_version: str = "implied-expectation-model:v0"

    def calculate(
        self,
        value: FundamentalAnchorInput | UnavailableFundamentalAnchorInput,
    ) -> ImpliedExpectationResult:
        if not isinstance(
            value,
            (FundamentalAnchorInput, UnavailableFundamentalAnchorInput),
        ):
            raise TypeError("value must be a fundamental anchor input")
        provenance = _merge_provenance(
            value.provenances,
            method_id=self.model_version,
        )
        input_method_versions = _method_lineage(value.provenances)
        metric = industry_valuation_policy_v0(value.industry_template_id).expectation_metric
        if isinstance(value, UnavailableFundamentalAnchorInput):
            return ImpliedExpectationResult(
                status=ValuationModelStatus.UNAVAILABLE,
                expectation_metric=metric,
                lower=None,
                upper=None,
                unit=MetricUnit.RATIO,
                assumptions=value.assumptions,
                invalidation_conditions=value.invalidation_conditions,
                provenance=provenance,
                input_method_versions=input_method_versions,
                unavailable_reasons=value.unavailable_reasons,
                model_version=self.model_version,
                scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
            )
        if value.method is FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK:
            candidates = tuple(
                (value.current_price / book) * (discount - growth) + growth
                for book in (
                    value.base_value_per_share_lower,
                    value.base_value_per_share_upper,
                )
                for discount in (
                    value.discount_rate_lower,
                    value.discount_rate_upper,
                )
                for growth in (
                    value.perpetual_growth_lower,
                    value.perpetual_growth_upper,
                )
            )
            lower = min(candidates)
            upper = max(candidates)
            metric = ValuationExpectationMetric.RETURN_ON_EQUITY
        else:
            lower = (
                value.current_price * value.discount_rate_lower - value.base_value_per_share_upper
            ) / (value.current_price + value.base_value_per_share_upper)
            upper = (
                value.current_price * value.discount_rate_upper - value.base_value_per_share_lower
            ) / (value.current_price + value.base_value_per_share_lower)
            metric = ValuationExpectationMetric.GROWTH
        if upper < lower:
            raise ValueError("anchor assumptions produce an invalid implied interval")
        return ImpliedExpectationResult(
            status=ValuationModelStatus.QUANTIFIED,
            expectation_metric=metric,
            lower=lower,
            upper=upper,
            unit=MetricUnit.RATIO,
            assumptions=value.assumptions,
            invalidation_conditions=value.invalidation_conditions,
            provenance=provenance,
            input_method_versions=input_method_versions,
            unavailable_reasons=(),
            model_version=self.model_version,
            scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
        )


def implied_expectation_model_v0() -> ImpliedExpectationModelV0:
    return ImpliedExpectationModelV0()


@dataclass(frozen=True)
class AnalystSourceAttestation:
    attestation_id: str
    provider_policy: ProviderFieldPolicy
    market: str
    provider_use: ProviderUse
    source_policy_version: str
    license_evidence_id: str
    approval_id: str
    qualified_at: datetime
    valid_until: datetime | None

    def __post_init__(self) -> None:
        for name in (
            "attestation_id",
            "market",
            "source_policy_version",
            "license_evidence_id",
            "approval_id",
        ):
            _text(getattr(self, name), name)
        if not isinstance(self.provider_policy, ProviderFieldPolicy):
            raise TypeError("provider_policy must be ProviderFieldPolicy")
        if self.provider_policy.field is not DataField.ANALYST_CONSENSUS:
            raise ValueError("analyst attestation requires analyst_consensus policy")
        if self.provider_policy.license_status is not LicenseStatus.VERIFIED:
            raise PermissionError("analyst source license must be verified")
        use = ProviderUse(self.provider_use)
        if not self.provider_policy.allows(use, self.market):
            raise PermissionError("provider policy does not allow the attested analyst use")
        qualified = _aware(self.qualified_at, "qualified_at")
        valid_until = None if self.valid_until is None else _aware(self.valid_until, "valid_until")
        if valid_until is not None and valid_until <= qualified:
            raise ValueError("valid_until must be later than qualified_at")
        object.__setattr__(self, "provider_use", use)


@dataclass(frozen=True)
class UnavailableAnalystRevisionInput:
    """Evidence that analyst consensus is unavailable, without invented snapshots."""

    expectation_metric: ValuationExpectationMetric
    unit: MetricUnit
    provenances: tuple[ValuationInputProvenance, ...]
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    latest_source_available_at: datetime | None
    unavailable_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        metric = ValuationExpectationMetric(self.expectation_metric)
        if MetricUnit(self.unit) is not MetricUnit.RATIO:
            raise ValueError("analyst revision unit must be ratio")
        provenances = tuple(self.provenances)
        if any(not isinstance(value, ValuationInputProvenance) for value in provenances):
            raise ValueError("unavailable analyst provenance evidence is invalid")
        reasons = _unique_reasons(self.unavailable_reasons)
        if not reasons:
            raise ValueError("unavailable analyst input requires reasons")
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        decision = _aware(self.decision_time, "decision_time")
        if trust is DataTrustState.RAW:
            raise ValueError("raw inputs cannot enter analyst revision")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError(
                "strict_historical analyst revision requires pit_verified inputs"
            )
        if self.latest_source_available_at is not None:
            available = _aware(
                self.latest_source_available_at,
                "latest_source_available_at",
            )
            if available > decision:
                raise ValueError("available_at cannot exceed decision_time")
        object.__setattr__(self, "expectation_metric", metric)
        object.__setattr__(self, "unit", MetricUnit.RATIO)
        object.__setattr__(self, "provenances", provenances)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class AnalystRevisionInput:
    expectation_metric: ValuationExpectationMetric
    current_lower: Decimal | None
    current_upper: Decimal | None
    prior_lower: Decimal | None
    prior_upper: Decimal | None
    unit: MetricUnit
    consensus_definition_version: str
    target_period_end: date
    forecast_horizon_days: int
    current_snapshot_at: datetime
    prior_snapshot_at: datetime
    source_attestation: AnalystSourceAttestation | None
    current_provider_id: str
    prior_provider_id: str
    current_provenance: ValuationInputProvenance
    prior_provenance: ValuationInputProvenance
    data_mode: DataMode
    trust_state: DataTrustState
    decision_time: datetime
    latest_source_available_at: datetime
    unavailable_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        metric = ValuationExpectationMetric(self.expectation_metric)
        if MetricUnit(self.unit) is not MetricUnit.RATIO:
            raise ValueError("analyst revision unit must be ratio")
        _text(self.consensus_definition_version, "consensus_definition_version")
        if not isinstance(self.target_period_end, date) or isinstance(
            self.target_period_end,
            datetime,
        ):
            raise TypeError("target_period_end must be a date")
        if not isinstance(self.forecast_horizon_days, int) or isinstance(
            self.forecast_horizon_days,
            bool,
        ):
            raise TypeError("forecast_horizon_days must be an integer")
        if self.forecast_horizon_days <= 0:
            raise ValueError("forecast_horizon_days must be positive")
        current_snapshot = _aware(self.current_snapshot_at, "current_snapshot_at")
        prior_snapshot = _aware(self.prior_snapshot_at, "prior_snapshot_at")
        if prior_snapshot >= current_snapshot:
            raise ValueError("prior_snapshot_at must precede current_snapshot_at")
        current_provider_id = _text(self.current_provider_id, "current_provider_id")
        prior_provider_id = _text(self.prior_provider_id, "prior_provider_id")
        for name in ("current_provenance", "prior_provenance"):
            if not isinstance(getattr(self, name), ValuationInputProvenance):
                raise TypeError(f"{name} must be ValuationInputProvenance")
        if self.source_attestation is not None and not isinstance(
            self.source_attestation,
            AnalystSourceAttestation,
        ):
            raise TypeError("source_attestation must be AnalystSourceAttestation or None")
        if self.source_attestation is not None:
            attested_provider_id = self.source_attestation.provider_policy.provider_id
            if current_provider_id != attested_provider_id or prior_provider_id != attested_provider_id:
                raise PermissionError(
                    "analyst consensus provider does not match source attestation"
                )
        mode, trust = _evidence_gate(
            data_mode=self.data_mode,
            trust_state=self.trust_state,
            decision_time=self.decision_time,
            latest_source_available_at=self.latest_source_available_at,
            label="analyst revision",
        )
        bounds = (
            self.current_lower,
            self.current_upper,
            self.prior_lower,
            self.prior_upper,
        )
        reasons = _unique_reasons(self.unavailable_reasons)
        if all(value is None for value in bounds):
            if not reasons:
                raise ValueError("missing analyst revision requires unavailable_reasons")
        elif any(value is None for value in bounds):
            raise ValueError("analyst revision bounds must be available together")
        else:
            assert self.current_lower is not None and self.current_upper is not None
            assert self.prior_lower is not None and self.prior_upper is not None
            _validate_interval(self.current_lower, self.current_upper, "current consensus")
            _validate_interval(self.prior_lower, self.prior_upper, "prior consensus")
            if reasons:
                raise ValueError("available analyst revision cannot carry reasons")
            if not isinstance(self.source_attestation, AnalystSourceAttestation):
                raise PermissionError("analyst revision values require source attestation")
            required_use = (
                ProviderUse.STRICT_HISTORICAL
                if mode is DataMode.STRICT_HISTORICAL
                else ProviderUse.PRIVATE_LOCAL_RESEARCH
            )
            if self.source_attestation.provider_use is not required_use:
                raise PermissionError("analyst source attestation use does not match data mode")
            if self.source_attestation.qualified_at > self.decision_time:
                raise PermissionError("analyst source was qualified after decision_time")
            if (
                self.source_attestation.valid_until is not None
                and self.source_attestation.valid_until < self.decision_time
            ):
                raise PermissionError("analyst source attestation expired before decision_time")
            trust_rank = {
                DataTrustState.RAW: 0,
                DataTrustState.NORMALIZED_CURRENT: 1,
                DataTrustState.PIT_VERIFIED: 2,
            }
            if (
                trust_rank[self.source_attestation.provider_policy.trust_ceiling]
                < trust_rank[trust]
            ):
                raise PermissionError("analyst source trust ceiling is below requested trust")
        if current_snapshot > self.latest_source_available_at:
            raise ValueError("current consensus snapshot exceeds source availability")
        object.__setattr__(self, "expectation_metric", metric)
        object.__setattr__(self, "unit", MetricUnit.RATIO)
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        object.__setattr__(self, "unavailable_reasons", reasons)


@dataclass(frozen=True)
class AnalystRevisionResult:
    status: ValuationModelStatus
    expectation_metric: ValuationExpectationMetric
    revision_lower: Decimal | None
    revision_upper: Decimal | None
    midpoint_revision: Decimal | None
    unit: MetricUnit
    consensus_definition_version: str | None
    target_period_end: date | None
    forecast_horizon_days: int | None
    current_snapshot_at: datetime | None
    prior_snapshot_at: datetime | None
    source_attestation_id: str | None
    source_policy_version: str | None
    current_provider_id: str | None
    prior_provider_id: str | None
    provenance: ValuationInputProvenance | None
    input_method_versions: tuple[str, ...]
    unavailable_reasons: tuple[str, ...]
    model_version: str
    scientific_status: ValuationModelScientificStatus


@dataclass(frozen=True)
class AnalystRevisionModelV0:
    model_version: str = "analyst-revision-model:v0"

    def calculate(
        self,
        value: AnalystRevisionInput | UnavailableAnalystRevisionInput,
    ) -> AnalystRevisionResult:
        if not isinstance(value, (AnalystRevisionInput, UnavailableAnalystRevisionInput)):
            raise TypeError("value must be an analyst revision input")
        if isinstance(value, UnavailableAnalystRevisionInput):
            provenance = (
                None
                if not value.provenances
                else _merge_provenance(value.provenances, method_id=self.model_version)
            )
            return AnalystRevisionResult(
                status=ValuationModelStatus.UNAVAILABLE,
                expectation_metric=value.expectation_metric,
                revision_lower=None,
                revision_upper=None,
                midpoint_revision=None,
                unit=value.unit,
                consensus_definition_version=None,
                target_period_end=None,
                forecast_horizon_days=None,
                current_snapshot_at=None,
                prior_snapshot_at=None,
                source_attestation_id=None,
                source_policy_version=None,
                current_provider_id=None,
                prior_provider_id=None,
                provenance=provenance,
                input_method_versions=_method_lineage(value.provenances),
                unavailable_reasons=value.unavailable_reasons,
                model_version=self.model_version,
                scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
            )
        provenances = (value.current_provenance, value.prior_provenance)
        provenance = _merge_provenance(
            provenances,
            method_id=self.model_version,
        )
        input_method_versions = _method_lineage(provenances)
        if value.current_lower is None:
            return AnalystRevisionResult(
                status=ValuationModelStatus.UNAVAILABLE,
                expectation_metric=value.expectation_metric,
                revision_lower=None,
                revision_upper=None,
                midpoint_revision=None,
                unit=value.unit,
                consensus_definition_version=value.consensus_definition_version,
                target_period_end=value.target_period_end,
                forecast_horizon_days=value.forecast_horizon_days,
                current_snapshot_at=value.current_snapshot_at,
                prior_snapshot_at=value.prior_snapshot_at,
                source_attestation_id=(
                    None
                    if value.source_attestation is None
                    else value.source_attestation.attestation_id
                ),
                source_policy_version=(
                    None
                    if value.source_attestation is None
                    else value.source_attestation.source_policy_version
                ),
                current_provider_id=value.current_provider_id,
                prior_provider_id=value.prior_provider_id,
                provenance=provenance,
                input_method_versions=input_method_versions,
                unavailable_reasons=value.unavailable_reasons,
                model_version=self.model_version,
                scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
            )
        assert value.current_upper is not None
        assert value.prior_lower is not None and value.prior_upper is not None
        assert value.source_attestation is not None
        return AnalystRevisionResult(
            status=ValuationModelStatus.QUANTIFIED,
            expectation_metric=value.expectation_metric,
            revision_lower=value.current_lower - value.prior_upper,
            revision_upper=value.current_upper - value.prior_lower,
            midpoint_revision=(
                (value.current_lower + value.current_upper) / Decimal(2)
                - (value.prior_lower + value.prior_upper) / Decimal(2)
            ),
            unit=value.unit,
            consensus_definition_version=value.consensus_definition_version,
            target_period_end=value.target_period_end,
            forecast_horizon_days=value.forecast_horizon_days,
            current_snapshot_at=value.current_snapshot_at,
            prior_snapshot_at=value.prior_snapshot_at,
            source_attestation_id=value.source_attestation.attestation_id,
            source_policy_version=value.source_attestation.source_policy_version,
            current_provider_id=value.current_provider_id,
            prior_provider_id=value.prior_provider_id,
            provenance=provenance,
            input_method_versions=input_method_versions,
            unavailable_reasons=(),
            model_version=self.model_version,
            scientific_status=ValuationModelScientificStatus.NOT_EVALUATED,
        )


def analyst_revision_model_v0() -> AnalystRevisionModelV0:
    return AnalystRevisionModelV0()


__all__ = [
    "AnalystRevisionInput",
    "AnalystRevisionModelV0",
    "AnalystRevisionResult",
    "AnalystSourceAttestation",
    "FundamentalAnchorInput",
    "FundamentalAnchorMethod",
    "FundamentalAnchorModelV0",
    "FundamentalAnchorResult",
    "ImpliedExpectationModelV0",
    "ImpliedExpectationResult",
    "IndustryValuationPolicy",
    "RelativeReferenceKind",
    "RelativeValuationComparison",
    "RelativeValuationModelV0",
    "RelativeValuationReferenceInput",
    "RelativeValuationResult",
    "UnavailableAnalystRevisionInput",
    "UnavailableFundamentalAnchorInput",
    "ValuationModelScientificStatus",
    "ValuationModelStatus",
    "analyst_revision_model_v0",
    "fundamental_anchor_model_v0",
    "implied_expectation_model_v0",
    "industry_valuation_policy_v0",
    "relative_valuation_model_v0",
]
