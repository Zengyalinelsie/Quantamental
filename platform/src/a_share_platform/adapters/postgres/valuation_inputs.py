"""PostgreSQL adapter for immutable frozen valuation/improvement input bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol, cast

import psycopg

from a_share_platform.domain.features import FeaturePeriod
from a_share_platform.domain.fundamental_improvement import (
    BaseEffectTreatment,
    FundamentalImprovementExposures,
    FundamentalImprovementInput,
    FundamentalImprovementMetric,
    ImprovementComparison,
    ImprovementInputProvenance,
    ImprovementWindow,
    OneOffTreatment,
    SeasonalityTreatment,
)
from a_share_platform.domain.industry_templates import IndustryTemplateId
from a_share_platform.domain.metrics import MetricUnit
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import (
    CoverageStatus,
    DataField,
    LicenseStatus,
    ProviderFieldPolicy,
    ProviderTier,
    ProviderUse,
)
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import (
    ValuationExpectationMetric,
    ValuationExpectationRangeInput,
    ValuationExpectationSource,
    ValuationExposures,
    ValuationInputProvenance,
    ValuationMetric,
    ValuationMetricInput,
)
from a_share_platform.domain.valuation_models import (
    AnalystRevisionInput,
    AnalystSourceAttestation,
    FundamentalAnchorInput,
    FundamentalAnchorMethod,
    IndustryValuationPolicy,
    RelativeReferenceKind,
    RelativeValuationReferenceInput,
    UnavailableAnalystRevisionInput,
    UnavailableFundamentalAnchorInput,
)
from a_share_platform.domain.valuation_scenarios import (
    ValuationScenario,
    ValuationScenarioInput,
    ValuationScenarioProvenance,
)
from a_share_platform.ports.valuation_inputs import (
    VALUATION_INPUT_BUNDLE_V1,
    VALUATION_INPUT_BUNDLE_V2,
    ValuationImprovementInputBundle,
    ValuationImprovementInputConflict,
    ValuationImprovementInputRequest,
    ValuationImprovementInputUnavailable,
    ValuationModelSuiteInputs,
)


def _json_parameter(value: object) -> object:
    try:
        from psycopg.types.json import Jsonb
    except ModuleNotFoundError:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return Jsonb(value)


def _json_value(value: object) -> object:
    if isinstance(value, str):
        return json.loads(value)
    return getattr(value, "obj", value)


def _mapping(value: object, field_name: str) -> Mapping[object, object]:
    parsed = _json_value(value)
    if not isinstance(parsed, Mapping):
        raise TypeError(f"stored {field_name} must be an object")
    return parsed


def _array(value: object, field_name: str) -> Sequence[object]:
    parsed = _json_value(value)
    if not isinstance(parsed, (list, tuple)):
        raise TypeError(f"stored {field_name} must be an array")
    return parsed


def _required(document: Mapping[object, object], name: str) -> object:
    if name not in document:
        raise ValueError(f"stored valuation input bundle is missing {name}")
    return document[name]


def _optional_decimal(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception as error:
        raise ValueError(f"stored {field_name} is not a Decimal") from error


def _required_decimal(value: object, field_name: str) -> Decimal:
    result = _optional_decimal(value, field_name)
    if result is None:
        raise ValueError(f"stored {field_name} must not be null")
    return result


def _datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value
    encoded = str(value)
    if encoded.endswith("Z"):
        encoded = encoded[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(encoded)
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO datetime") from error


def _date(value: object, field_name: str) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as error:
        raise ValueError(f"stored {field_name} is not an ISO date") from error


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    values = _array(value, field_name)
    if any(not isinstance(item, str) for item in values):
        raise TypeError(f"stored {field_name} must contain strings")
    return tuple(cast(str, item) for item in values)


def _valuation_provenance(value: object) -> ValuationInputProvenance:
    document = _mapping(value, "valuation provenance")
    return ValuationInputProvenance(
        dataset_version_id=str(_required(document, "dataset_version_id")),
        method_id=str(_required(document, "method_id")),
        method_version=str(_required(document, "method_version")),
        source_observation_ids=_strings(
            _required(document, "source_observation_ids"),
            "source_observation_ids",
        ),
        content_hashes=_strings(_required(document, "content_hashes"), "content_hashes"),
        additional_dataset_version_ids=_strings(
            document.get("additional_dataset_version_ids", []),
            "additional_dataset_version_ids",
        ),
    )


def _valuation_metric(value: object) -> ValuationMetricInput:
    document = _mapping(value, "valuation metric input")
    return ValuationMetricInput(
        metric=ValuationMetric(str(_required(document, "metric"))),
        numerator=_optional_decimal(document.get("numerator"), "numerator"),
        denominator=_optional_decimal(document.get("denominator"), "denominator"),
        numerator_unit=MetricUnit(str(_required(document, "numerator_unit"))),
        numerator_period=FeaturePeriod(str(_required(document, "numerator_period"))),
        denominator_unit=MetricUnit(str(_required(document, "denominator_unit"))),
        denominator_period=FeaturePeriod(str(_required(document, "denominator_period"))),
        currency=str(_required(document, "currency")),
        provenance=_valuation_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"),
            "unavailable_reasons",
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _expectation(value: object) -> ValuationExpectationRangeInput:
    document = _mapping(value, "valuation expectation input")
    return ValuationExpectationRangeInput(
        source=ValuationExpectationSource(str(_required(document, "source"))),
        expectation_metric=ValuationExpectationMetric(
            str(_required(document, "expectation_metric"))
        ),
        lower=_optional_decimal(document.get("lower"), "lower"),
        upper=_optional_decimal(document.get("upper"), "upper"),
        unit=MetricUnit(str(_required(document, "unit"))),
        assumptions=_strings(_required(document, "assumptions"), "assumptions"),
        invalidation_conditions=_strings(
            _required(document, "invalidation_conditions"),
            "invalidation_conditions",
        ),
        provenance=_valuation_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"),
            "unavailable_reasons",
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _improvement_provenance(value: object) -> ImprovementInputProvenance:
    document = _mapping(value, "improvement provenance")
    return ImprovementInputProvenance(
        dataset_version_id=str(_required(document, "dataset_version_id")),
        source_version_id=str(_required(document, "source_version_id")),
        mapping_version_id=str(_required(document, "mapping_version_id")),
        metric_definition_id=str(_required(document, "metric_definition_id")),
        metric_definition_version=str(_required(document, "metric_definition_version")),
        source_fact_ids=_strings(_required(document, "source_fact_ids"), "source_fact_ids"),
        content_hashes=_strings(_required(document, "content_hashes"), "content_hashes"),
        additional_dataset_version_ids=_strings(
            document.get("additional_dataset_version_ids", []),
            "additional_dataset_version_ids",
        ),
    )


def _improvement(value: object) -> FundamentalImprovementInput:
    document = _mapping(value, "improvement input")
    return FundamentalImprovementInput(
        metric=FundamentalImprovementMetric(str(_required(document, "metric"))),
        level=_optional_decimal(document.get("level"), "level"),
        current_change=_optional_decimal(document.get("current_change"), "current_change"),
        prior_change=_optional_decimal(document.get("prior_change"), "prior_change"),
        level_unit=MetricUnit(str(_required(document, "level_unit"))),
        change_unit=MetricUnit(str(_required(document, "change_unit"))),
        currency=None if document.get("currency") is None else str(document["currency"]),
        comparison=ImprovementComparison(str(_required(document, "comparison"))),
        window=ImprovementWindow(str(_required(document, "window"))),
        current_period_end=_date(
            _required(document, "current_period_end"), "current_period_end"
        ),
        current_comparison_period_end=_date(
            _required(document, "current_comparison_period_end"),
            "current_comparison_period_end",
        ),
        prior_period_end=_date(_required(document, "prior_period_end"), "prior_period_end"),
        prior_comparison_period_end=_date(
            _required(document, "prior_comparison_period_end"),
            "prior_comparison_period_end",
        ),
        seasonality_treatment=SeasonalityTreatment(
            str(_required(document, "seasonality_treatment"))
        ),
        base_effect_treatment=BaseEffectTreatment(
            str(_required(document, "base_effect_treatment"))
        ),
        one_off_treatment=OneOffTreatment(str(_required(document, "one_off_treatment"))),
        provenance=_improvement_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"), "unavailable_reasons"
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _scenario_provenance(value: object) -> ValuationScenarioProvenance:
    document = _mapping(value, "scenario provenance")
    return ValuationScenarioProvenance(
        dataset_version_id=str(_required(document, "dataset_version_id")),
        source_observation_ids=_strings(
            _required(document, "source_observation_ids"), "source_observation_ids"
        ),
        content_hashes=_strings(_required(document, "content_hashes"), "content_hashes"),
        additional_dataset_version_ids=_strings(
            document.get("additional_dataset_version_ids", []),
            "additional_dataset_version_ids",
        ),
    )


def _scenario(value: object) -> ValuationScenarioInput:
    document = _mapping(value, "scenario input")
    return ValuationScenarioInput(
        scenario=ValuationScenario(str(_required(document, "scenario"))),
        driver_lower=_optional_decimal(document.get("driver_lower"), "driver_lower"),
        driver_upper=_optional_decimal(document.get("driver_upper"), "driver_upper"),
        driver_unit=MetricUnit(str(_required(document, "driver_unit"))),
        assumptions=_strings(_required(document, "assumptions"), "assumptions"),
        provenance=_scenario_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"), "unavailable_reasons"
        ),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
    )


def _provenance_document(value: object) -> dict[str, object]:
    if isinstance(value, ValuationInputProvenance):
        return {
            "dataset_version_id": value.dataset_version_id,
            "method_id": value.method_id,
            "method_version": value.method_version,
            "source_observation_ids": list(value.source_observation_ids),
            "content_hashes": list(value.content_hashes),
            "additional_dataset_version_ids": list(value.additional_dataset_version_ids),
        }
    if isinstance(value, ImprovementInputProvenance):
        return {
            "dataset_version_id": value.dataset_version_id,
            "source_version_id": value.source_version_id,
            "mapping_version_id": value.mapping_version_id,
            "metric_definition_id": value.metric_definition_id,
            "metric_definition_version": value.metric_definition_version,
            "source_fact_ids": list(value.source_fact_ids),
            "content_hashes": list(value.content_hashes),
            "additional_dataset_version_ids": list(value.additional_dataset_version_ids),
        }
    if isinstance(value, ValuationScenarioProvenance):
        return {
            "dataset_version_id": value.dataset_version_id,
            "source_observation_ids": list(value.source_observation_ids),
            "content_hashes": list(value.content_hashes),
            "additional_dataset_version_ids": list(value.additional_dataset_version_ids),
        }
    raise TypeError("unsupported valuation bundle provenance")


def _valuation_metric_document(value: ValuationMetricInput) -> dict[str, object]:
    return {
        "metric": value.metric.value,
        "numerator": None if value.numerator is None else str(value.numerator),
        "denominator": None if value.denominator is None else str(value.denominator),
        "numerator_unit": value.numerator_unit.value,
        "numerator_period": value.numerator_period.value,
        "denominator_unit": value.denominator_unit.value,
        "denominator_period": value.denominator_period.value,
        "currency": value.currency,
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _expectation_document(value: ValuationExpectationRangeInput) -> dict[str, object]:
    return {
        "source": value.source.value,
        "expectation_metric": value.expectation_metric.value,
        "lower": None if value.lower is None else str(value.lower),
        "upper": None if value.upper is None else str(value.upper),
        "unit": value.unit.value,
        "assumptions": list(value.assumptions),
        "invalidation_conditions": list(value.invalidation_conditions),
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _improvement_document(value: FundamentalImprovementInput) -> dict[str, object]:
    return {
        "metric": value.metric.value,
        "level": None if value.level is None else str(value.level),
        "current_change": None if value.current_change is None else str(value.current_change),
        "prior_change": None if value.prior_change is None else str(value.prior_change),
        "level_unit": value.level_unit.value,
        "change_unit": value.change_unit.value,
        "currency": value.currency,
        "comparison": value.comparison.value,
        "window": value.window.value,
        "current_period_end": value.current_period_end.isoformat(),
        "current_comparison_period_end": value.current_comparison_period_end.isoformat(),
        "prior_period_end": value.prior_period_end.isoformat(),
        "prior_comparison_period_end": value.prior_comparison_period_end.isoformat(),
        "seasonality_treatment": value.seasonality_treatment.value,
        "base_effect_treatment": value.base_effect_treatment.value,
        "one_off_treatment": value.one_off_treatment.value,
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _scenario_document(value: ValuationScenarioInput) -> dict[str, object]:
    return {
        "scenario": value.scenario.value,
        "driver_lower": None if value.driver_lower is None else str(value.driver_lower),
        "driver_upper": None if value.driver_upper is None else str(value.driver_upper),
        "driver_unit": value.driver_unit.value,
        "assumptions": list(value.assumptions),
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "unavailable_reasons": list(value.unavailable_reasons),
        "decision_time": value.decision_time.isoformat() if value.decision_time else None,
        "latest_source_available_at": (
            value.latest_source_available_at.isoformat()
            if value.latest_source_available_at
            else None
        ),
    }


def _industry_policy_document(value: IndustryValuationPolicy) -> dict[str, object]:
    return {
        "industry_template_id": value.industry_template_id.value,
        "anchor_method": value.anchor_method.value,
        "expectation_metric": value.expectation_metric.value,
        "relative_metrics": [item.value for item in value.relative_metrics],
        "policy_version": value.policy_version,
    }


def _industry_policy(value: object) -> IndustryValuationPolicy:
    document = _mapping(value, "industry valuation policy")
    return IndustryValuationPolicy(
        industry_template_id=IndustryTemplateId(
            str(_required(document, "industry_template_id"))
        ),
        anchor_method=FundamentalAnchorMethod(str(_required(document, "anchor_method"))),
        expectation_metric=ValuationExpectationMetric(
            str(_required(document, "expectation_metric"))
        ),
        relative_metrics=tuple(
            ValuationMetric(str(item))
            for item in _array(_required(document, "relative_metrics"), "relative_metrics")
        ),
        policy_version=str(_required(document, "policy_version")),
    )


def _relative_reference_document(
    value: RelativeValuationReferenceInput,
) -> dict[str, object]:
    return {
        "metric": value.metric.value,
        "reference_kind": value.reference_kind.value,
        "median_value": None if value.median_value is None else str(value.median_value),
        "observation_count": value.observation_count,
        "unit": value.unit.value,
        "comparable_set_version_id": value.comparable_set_version_id,
        "provenance": _provenance_document(value.provenance),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "decision_time": value.decision_time.isoformat(),
        "latest_source_available_at": value.latest_source_available_at.isoformat(),
        "unavailable_reasons": list(value.unavailable_reasons),
    }


def _relative_reference(value: object) -> RelativeValuationReferenceInput:
    document = _mapping(value, "relative valuation reference")
    observation_count = _required(document, "observation_count")
    if not isinstance(observation_count, int) or isinstance(observation_count, bool):
        raise TypeError("stored observation_count must be an integer")
    return RelativeValuationReferenceInput(
        metric=ValuationMetric(str(_required(document, "metric"))),
        reference_kind=RelativeReferenceKind(str(_required(document, "reference_kind"))),
        median_value=_optional_decimal(document.get("median_value"), "median_value"),
        observation_count=observation_count,
        unit=MetricUnit(str(_required(document, "unit"))),
        comparable_set_version_id=str(_required(document, "comparable_set_version_id")),
        provenance=_valuation_provenance(_required(document, "provenance")),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
        unavailable_reasons=_strings(
            _required(document, "unavailable_reasons"),
            "unavailable_reasons",
        ),
    )


def _anchor_document(
    value: FundamentalAnchorInput | UnavailableFundamentalAnchorInput,
) -> dict[str, object]:
    common: dict[str, object] = {
        "method": value.method.value,
        "industry_template_id": value.industry_template_id.value,
        "currency": value.currency,
        "current_price_unit": value.current_price_unit.value,
        "base_value_per_share_unit": value.base_value_per_share_unit.value,
        "rate_unit": value.rate_unit.value,
        "assumptions": list(value.assumptions),
        "invalidation_conditions": list(value.invalidation_conditions),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "decision_time": value.decision_time.isoformat(),
        "latest_source_available_at": value.latest_source_available_at.isoformat(),
    }
    if isinstance(value, UnavailableFundamentalAnchorInput):
        return {
            **common,
            "availability": "unavailable",
            "provenances": [_provenance_document(item) for item in value.provenances],
            "unavailable_reasons": list(value.unavailable_reasons),
        }
    return {
        **common,
        "availability": "available",
        "current_price": str(value.current_price),
        "base_value_per_share_lower": str(value.base_value_per_share_lower),
        "base_value_per_share_upper": str(value.base_value_per_share_upper),
        "profitability_lower": (
            None if value.profitability_lower is None else str(value.profitability_lower)
        ),
        "profitability_upper": (
            None if value.profitability_upper is None else str(value.profitability_upper)
        ),
        "discount_rate_lower": str(value.discount_rate_lower),
        "discount_rate_upper": str(value.discount_rate_upper),
        "perpetual_growth_lower": str(value.perpetual_growth_lower),
        "perpetual_growth_upper": str(value.perpetual_growth_upper),
        "price_provenance": _provenance_document(value.price_provenance),
        "fundamental_provenance": _provenance_document(value.fundamental_provenance),
        "assumption_provenance": _provenance_document(value.assumption_provenance),
    }


def _anchor(value: object) -> FundamentalAnchorInput | UnavailableFundamentalAnchorInput:
    document = _mapping(value, "fundamental anchor input")
    method = FundamentalAnchorMethod(str(_required(document, "method")))
    template = IndustryTemplateId(str(_required(document, "industry_template_id")))
    currency = str(_required(document, "currency"))
    current_price_unit = MetricUnit(str(_required(document, "current_price_unit")))
    base_value_unit = MetricUnit(str(_required(document, "base_value_per_share_unit")))
    rate_unit = MetricUnit(str(_required(document, "rate_unit")))
    assumptions = _strings(_required(document, "assumptions"), "assumptions")
    invalidations = _strings(
        _required(document, "invalidation_conditions"),
        "invalidation_conditions",
    )
    data_mode = DataMode(str(_required(document, "data_mode")))
    trust_state = DataTrustState(str(_required(document, "trust_state")))
    decision_time = _datetime(_required(document, "decision_time"), "decision_time")
    latest_available = _datetime(
        _required(document, "latest_source_available_at"),
        "latest_source_available_at",
    )
    availability = str(_required(document, "availability"))
    if availability == "unavailable":
        return UnavailableFundamentalAnchorInput(
            method=method,
            industry_template_id=template,
            currency=currency,
            current_price_unit=current_price_unit,
            base_value_per_share_unit=base_value_unit,
            rate_unit=rate_unit,
            assumptions=assumptions,
            invalidation_conditions=invalidations,
            provenances=tuple(
                _valuation_provenance(item)
                for item in _array(_required(document, "provenances"), "provenances")
            ),
            data_mode=data_mode,
            trust_state=trust_state,
            decision_time=decision_time,
            latest_source_available_at=latest_available,
            unavailable_reasons=_strings(
                _required(document, "unavailable_reasons"),
                "unavailable_reasons",
            ),
        )
    if availability != "available":
        raise ValueError("stored fundamental anchor availability is unknown")
    return FundamentalAnchorInput(
        method=method,
        industry_template_id=template,
        current_price=_required_decimal(
            _required(document, "current_price"),
            "current_price",
        ),
        base_value_per_share_lower=_required_decimal(
            _required(document, "base_value_per_share_lower"),
            "base_value_per_share_lower",
        ),
        base_value_per_share_upper=_required_decimal(
            _required(document, "base_value_per_share_upper"),
            "base_value_per_share_upper",
        ),
        profitability_lower=_optional_decimal(
            document.get("profitability_lower"), "profitability_lower"
        ),
        profitability_upper=_optional_decimal(
            document.get("profitability_upper"), "profitability_upper"
        ),
        discount_rate_lower=_required_decimal(
            _required(document, "discount_rate_lower"),
            "discount_rate_lower",
        ),
        discount_rate_upper=_required_decimal(
            _required(document, "discount_rate_upper"),
            "discount_rate_upper",
        ),
        perpetual_growth_lower=_required_decimal(
            _required(document, "perpetual_growth_lower"),
            "perpetual_growth_lower",
        ),
        perpetual_growth_upper=_required_decimal(
            _required(document, "perpetual_growth_upper"),
            "perpetual_growth_upper",
        ),
        current_price_unit=current_price_unit,
        base_value_per_share_unit=base_value_unit,
        rate_unit=rate_unit,
        currency=currency,
        assumptions=assumptions,
        invalidation_conditions=invalidations,
        price_provenance=_valuation_provenance(_required(document, "price_provenance")),
        fundamental_provenance=_valuation_provenance(
            _required(document, "fundamental_provenance")
        ),
        assumption_provenance=_valuation_provenance(
            _required(document, "assumption_provenance")
        ),
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=decision_time,
        latest_source_available_at=latest_available,
    )


def _provider_policy_document(value: ProviderFieldPolicy) -> dict[str, object]:
    return {
        "provider_id": value.provider_id,
        "field": value.field.value,
        "tier": value.tier.value,
        "markets": sorted(value.markets),
        "permitted_uses": sorted(item.value for item in value.permitted_uses),
        "license_status": value.license_status.value,
        "trust_ceiling": value.trust_ceiling.value,
        "coverage": value.coverage.value,
        "warning": value.warning,
        "retention_prohibited": value.retention_prohibited,
    }


def _provider_policy(value: object) -> ProviderFieldPolicy:
    document = _mapping(value, "provider field policy")
    retention = _required(document, "retention_prohibited")
    if not isinstance(retention, bool):
        raise TypeError("stored retention_prohibited must be a boolean")
    return ProviderFieldPolicy(
        provider_id=str(_required(document, "provider_id")),
        field=DataField(str(_required(document, "field"))),
        tier=ProviderTier(str(_required(document, "tier"))),
        markets=frozenset(_strings(_required(document, "markets"), "markets")),
        permitted_uses=frozenset(
            ProviderUse(item)
            for item in _strings(_required(document, "permitted_uses"), "permitted_uses")
        ),
        license_status=LicenseStatus(str(_required(document, "license_status"))),
        trust_ceiling=DataTrustState(str(_required(document, "trust_ceiling"))),
        coverage=CoverageStatus(str(_required(document, "coverage"))),
        warning=str(_required(document, "warning")),
        retention_prohibited=retention,
    )


def _attestation_document(value: AnalystSourceAttestation) -> dict[str, object]:
    return {
        "attestation_id": value.attestation_id,
        "provider_policy": _provider_policy_document(value.provider_policy),
        "market": value.market,
        "provider_use": value.provider_use.value,
        "source_policy_version": value.source_policy_version,
        "license_evidence_id": value.license_evidence_id,
        "approval_id": value.approval_id,
        "qualified_at": value.qualified_at.isoformat(),
        "valid_until": None if value.valid_until is None else value.valid_until.isoformat(),
    }


def _attestation(value: object) -> AnalystSourceAttestation:
    document = _mapping(value, "analyst source attestation")
    return AnalystSourceAttestation(
        attestation_id=str(_required(document, "attestation_id")),
        provider_policy=_provider_policy(_required(document, "provider_policy")),
        market=str(_required(document, "market")),
        provider_use=ProviderUse(str(_required(document, "provider_use"))),
        source_policy_version=str(_required(document, "source_policy_version")),
        license_evidence_id=str(_required(document, "license_evidence_id")),
        approval_id=str(_required(document, "approval_id")),
        qualified_at=_datetime(_required(document, "qualified_at"), "qualified_at"),
        valid_until=(
            None
            if document.get("valid_until") is None
            else _datetime(document["valid_until"], "valid_until")
        ),
    )


def _analyst_document(
    value: AnalystRevisionInput | UnavailableAnalystRevisionInput,
) -> dict[str, object]:
    common: dict[str, object] = {
        "expectation_metric": value.expectation_metric.value,
        "unit": value.unit.value,
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "decision_time": value.decision_time.isoformat(),
        "latest_source_available_at": (
            None
            if value.latest_source_available_at is None
            else value.latest_source_available_at.isoformat()
        ),
        "unavailable_reasons": list(value.unavailable_reasons),
    }
    if isinstance(value, UnavailableAnalystRevisionInput):
        return {
            **common,
            "availability": "unavailable",
            "provenances": [_provenance_document(item) for item in value.provenances],
        }
    return {
        **common,
        "availability": "available",
        "current_lower": None if value.current_lower is None else str(value.current_lower),
        "current_upper": None if value.current_upper is None else str(value.current_upper),
        "prior_lower": None if value.prior_lower is None else str(value.prior_lower),
        "prior_upper": None if value.prior_upper is None else str(value.prior_upper),
        "consensus_definition_version": value.consensus_definition_version,
        "target_period_end": value.target_period_end.isoformat(),
        "forecast_horizon_days": value.forecast_horizon_days,
        "current_snapshot_at": value.current_snapshot_at.isoformat(),
        "prior_snapshot_at": value.prior_snapshot_at.isoformat(),
        "source_attestation": (
            None
            if value.source_attestation is None
            else _attestation_document(value.source_attestation)
        ),
        "current_provider_id": value.current_provider_id,
        "prior_provider_id": value.prior_provider_id,
        "current_provenance": _provenance_document(value.current_provenance),
        "prior_provenance": _provenance_document(value.prior_provenance),
    }


def _analyst(value: object) -> AnalystRevisionInput | UnavailableAnalystRevisionInput:
    document = _mapping(value, "analyst revision input")
    metric = ValuationExpectationMetric(str(_required(document, "expectation_metric")))
    unit = MetricUnit(str(_required(document, "unit")))
    data_mode = DataMode(str(_required(document, "data_mode")))
    trust_state = DataTrustState(str(_required(document, "trust_state")))
    decision_time = _datetime(_required(document, "decision_time"), "decision_time")
    latest_available = (
        None
        if document.get("latest_source_available_at") is None
        else _datetime(
            document["latest_source_available_at"],
            "latest_source_available_at",
        )
    )
    reasons = _strings(
        _required(document, "unavailable_reasons"),
        "unavailable_reasons",
    )
    availability = str(_required(document, "availability"))
    if availability == "unavailable":
        return UnavailableAnalystRevisionInput(
            expectation_metric=metric,
            unit=unit,
            provenances=tuple(
                _valuation_provenance(item)
                for item in _array(_required(document, "provenances"), "provenances")
            ),
            data_mode=data_mode,
            trust_state=trust_state,
            decision_time=decision_time,
            latest_source_available_at=latest_available,
            unavailable_reasons=reasons,
        )
    if availability != "available":
        raise ValueError("stored analyst revision availability is unknown")
    horizon = _required(document, "forecast_horizon_days")
    if not isinstance(horizon, int) or isinstance(horizon, bool):
        raise TypeError("stored forecast_horizon_days must be an integer")
    attestation = document.get("source_attestation")
    if latest_available is None:
        raise ValueError("available analyst revision requires latest_source_available_at")
    return AnalystRevisionInput(
        expectation_metric=metric,
        current_lower=_optional_decimal(document.get("current_lower"), "current_lower"),
        current_upper=_optional_decimal(document.get("current_upper"), "current_upper"),
        prior_lower=_optional_decimal(document.get("prior_lower"), "prior_lower"),
        prior_upper=_optional_decimal(document.get("prior_upper"), "prior_upper"),
        unit=unit,
        consensus_definition_version=str(
            _required(document, "consensus_definition_version")
        ),
        target_period_end=_date(_required(document, "target_period_end"), "target_period_end"),
        forecast_horizon_days=horizon,
        current_snapshot_at=_datetime(
            _required(document, "current_snapshot_at"), "current_snapshot_at"
        ),
        prior_snapshot_at=_datetime(
            _required(document, "prior_snapshot_at"), "prior_snapshot_at"
        ),
        source_attestation=None if attestation is None else _attestation(attestation),
        current_provider_id=str(_required(document, "current_provider_id")),
        prior_provider_id=str(_required(document, "prior_provider_id")),
        current_provenance=_valuation_provenance(
            _required(document, "current_provenance")
        ),
        prior_provenance=_valuation_provenance(_required(document, "prior_provenance")),
        data_mode=data_mode,
        trust_state=trust_state,
        decision_time=decision_time,
        latest_source_available_at=latest_available,
        unavailable_reasons=reasons,
    )


def _suite_document(value: ValuationModelSuiteInputs) -> dict[str, object]:
    return {
        "industry_policy": _industry_policy_document(value.industry_policy),
        "relative_references": [
            _relative_reference_document(item) for item in value.relative_references
        ],
        "fundamental_anchor_input": _anchor_document(value.fundamental_anchor_input),
        "analyst_revision_input": _analyst_document(value.analyst_revision_input),
        "relative_model_version": value.relative_model_version,
        "fundamental_anchor_model_version": value.fundamental_anchor_model_version,
        "implied_expectation_model_version": value.implied_expectation_model_version,
        "analyst_revision_model_version": value.analyst_revision_model_version,
        "bundle_compiler_version": value.bundle_compiler_version,
    }


def _suite(value: object) -> ValuationModelSuiteInputs:
    document = _mapping(value, "valuation model suite inputs")
    return ValuationModelSuiteInputs(
        industry_policy=_industry_policy(_required(document, "industry_policy")),
        relative_references=tuple(
            _relative_reference(item)
            for item in _array(
                _required(document, "relative_references"),
                "relative_references",
            )
        ),
        fundamental_anchor_input=_anchor(_required(document, "fundamental_anchor_input")),
        analyst_revision_input=_analyst(_required(document, "analyst_revision_input")),
        relative_model_version=str(_required(document, "relative_model_version")),
        fundamental_anchor_model_version=str(
            _required(document, "fundamental_anchor_model_version")
        ),
        implied_expectation_model_version=str(
            _required(document, "implied_expectation_model_version")
        ),
        analyst_revision_model_version=str(
            _required(document, "analyst_revision_model_version")
        ),
        bundle_compiler_version=str(_required(document, "bundle_compiler_version")),
    )


def bundle_document(value: ValuationImprovementInputBundle) -> dict[str, object]:
    """Return a complete canonical JSON-compatible frozen bundle document."""

    if not isinstance(value, ValuationImprovementInputBundle):
        raise TypeError("value must be a ValuationImprovementInputBundle")
    document: dict[str, object] = {
        "bundle_version_id": value.bundle_version_id,
        "security_id": value.security_id,
        "decision_time": value.decision_time.isoformat(),
        "latest_source_available_at": value.latest_source_available_at.isoformat(),
        "data_mode": value.data_mode.value,
        "trust_state": value.trust_state.value,
        "dataset_version_ids": list(value.dataset_version_ids),
        "industry_template_id": value.industry_template_id.value,
        "valuation_formula_version": value.valuation_formula_version,
        "improvement_formula_version": value.improvement_formula_version,
        "scenario_method_id": value.scenario_method_id,
        "scenario_method_version": value.scenario_method_version,
        "valuation_metric_inputs": [
            _valuation_metric_document(item) for item in value.valuation_metric_inputs
        ],
        "valuation_exposures": {
            "industry_code": value.valuation_exposures.industry_code,
            "log_market_cap": (
                None
                if value.valuation_exposures.log_market_cap is None
                else str(value.valuation_exposures.log_market_cap)
            ),
            "beta": (
                None
                if value.valuation_exposures.beta is None
                else str(value.valuation_exposures.beta)
            ),
        },
        "currency": value.currency,
        "comparable_set_version_id": value.comparable_set_version_id,
        "improvement_inputs": [
            _improvement_document(item) for item in value.improvement_inputs
        ],
        "improvement_exposures": {
            "industry_code": value.improvement_exposures.industry_code,
            "log_market_cap": (
                None
                if value.improvement_exposures.log_market_cap is None
                else str(value.improvement_exposures.log_market_cap)
            ),
            "beta": (
                None
                if value.improvement_exposures.beta is None
                else str(value.improvement_exposures.beta)
            ),
        },
        "scenario_inputs": [_scenario_document(item) for item in value.scenario_inputs],
    }
    if value.document_schema_version == VALUATION_INPUT_BUNDLE_V1:
        assert value.market_implied is not None and value.fundamental_anchor is not None
        document.update(
            {
                "market_implied": _expectation_document(value.market_implied),
                "fundamental_anchor": _expectation_document(value.fundamental_anchor),
            }
        )
        return document
    if value.document_schema_version != VALUATION_INPUT_BUNDLE_V2:
        raise ValueError(f"unknown valuation input bundle schema: {value.document_schema_version}")
    assert value.valuation_model_suite_inputs is not None
    document.update(
        {
            "document_schema_version": VALUATION_INPUT_BUNDLE_V2,
            "valuation_model_suite_inputs": _suite_document(
                value.valuation_model_suite_inputs
            ),
        }
    )
    return document


def bundle_from_document(value: object) -> ValuationImprovementInputBundle:
    """Reconstruct domain values so every invariant is revalidated on read."""

    document = _mapping(value, "valuation input bundle")
    schema_version = str(document.get("document_schema_version", VALUATION_INPUT_BUNDLE_V1))
    if schema_version not in {VALUATION_INPUT_BUNDLE_V1, VALUATION_INPUT_BUNDLE_V2}:
        raise ValueError(f"unknown valuation input bundle schema: {schema_version}")
    valuation_exposures = _mapping(
        _required(document, "valuation_exposures"), "valuation_exposures"
    )
    improvement_exposures = _mapping(
        _required(document, "improvement_exposures"), "improvement_exposures"
    )
    return ValuationImprovementInputBundle(
        bundle_version_id=str(_required(document, "bundle_version_id")),
        security_id=str(_required(document, "security_id")),
        decision_time=_datetime(_required(document, "decision_time"), "decision_time"),
        latest_source_available_at=_datetime(
            _required(document, "latest_source_available_at"),
            "latest_source_available_at",
        ),
        data_mode=DataMode(str(_required(document, "data_mode"))),
        trust_state=DataTrustState(str(_required(document, "trust_state"))),
        dataset_version_ids=_strings(
            _required(document, "dataset_version_ids"), "dataset_version_ids"
        ),
        industry_template_id=IndustryTemplateId(
            str(_required(document, "industry_template_id"))
        ),
        valuation_formula_version=str(_required(document, "valuation_formula_version")),
        improvement_formula_version=str(_required(document, "improvement_formula_version")),
        scenario_method_id=str(_required(document, "scenario_method_id")),
        scenario_method_version=str(_required(document, "scenario_method_version")),
        valuation_metric_inputs=tuple(
            _valuation_metric(item)
            for item in _array(
                _required(document, "valuation_metric_inputs"),
                "valuation_metric_inputs",
            )
        ),
        market_implied=(
            _expectation(_required(document, "market_implied"))
            if schema_version == VALUATION_INPUT_BUNDLE_V1
            else None
        ),
        fundamental_anchor=(
            _expectation(_required(document, "fundamental_anchor"))
            if schema_version == VALUATION_INPUT_BUNDLE_V1
            else None
        ),
        valuation_exposures=ValuationExposures(
            industry_code=(
                None
                if valuation_exposures.get("industry_code") is None
                else str(valuation_exposures["industry_code"])
            ),
            log_market_cap=_optional_decimal(
                valuation_exposures.get("log_market_cap"), "log_market_cap"
            ),
            beta=_optional_decimal(valuation_exposures.get("beta"), "beta"),
        ),
        currency=str(_required(document, "currency")),
        comparable_set_version_id=str(_required(document, "comparable_set_version_id")),
        improvement_inputs=tuple(
            _improvement(item)
            for item in _array(_required(document, "improvement_inputs"), "improvement_inputs")
        ),
        improvement_exposures=FundamentalImprovementExposures(
            industry_code=(
                None
                if improvement_exposures.get("industry_code") is None
                else str(improvement_exposures["industry_code"])
            ),
            log_market_cap=_optional_decimal(
                improvement_exposures.get("log_market_cap"), "log_market_cap"
            ),
            beta=_optional_decimal(improvement_exposures.get("beta"), "beta"),
        ),
        scenario_inputs=tuple(
            _scenario(item)
            for item in _array(_required(document, "scenario_inputs"), "scenario_inputs")
        ),
        document_schema_version=schema_version,
        valuation_model_suite_inputs=(
            None
            if schema_version == VALUATION_INPUT_BUNDLE_V1
            else _suite(_required(document, "valuation_model_suite_inputs"))
        ),
    )


def bundle_content_hash(value: ValuationImprovementInputBundle) -> str:
    encoded = json.dumps(
        bundle_document(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class QueryResult(Protocol):
    def fetchone(self) -> tuple[object, ...] | None: ...


class Transaction(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool | None: ...


class Connection(Protocol):
    def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> QueryResult: ...

    def transaction(self) -> Transaction: ...


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]


class PostgresValuationImprovementInputRepository:
    """Append and exact-key load complete frozen input bundles; never synthesise one."""

    def __init__(self, connection_factory: ConnectionFactory) -> None:
        self._connection_factory = connection_factory

    @classmethod
    def from_dsn(cls, dsn: str) -> PostgresValuationImprovementInputRepository:
        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("database DSN must not be empty")

        def connect() -> AbstractContextManager[Connection]:
            return cast(AbstractContextManager[Connection], psycopg.connect(dsn))

        return cls(connect)

    def append(
        self,
        value: ValuationImprovementInputBundle,
    ) -> ValuationImprovementInputBundle:
        if not isinstance(value, ValuationImprovementInputBundle):
            raise TypeError("value must be a ValuationImprovementInputBundle")
        if value.document_schema_version != VALUATION_INPUT_BUNDLE_V2:
            raise ValueError("new frozen valuation input writes require bundle v2")
        try:
            with self._connection_factory() as connection, connection.transaction():
                existing = self._load_by_id(connection, value.bundle_version_id)
                if existing is not None:
                    if bundle_content_hash(existing) != bundle_content_hash(value):
                        raise ValuationImprovementInputConflict(
                            f"immutable valuation input bundle conflict: {value.bundle_version_id}"
                        )
                    return existing
                row = self.to_row(value)
                connection.execute(
                    """
                    INSERT INTO research.valuation_input_bundles (
                        bundle_version_id, security_id, decision_time, content_hash,
                        data_mode, trust_state, latest_source_available_at,
                        document_schema_version, dataset_version_ids, bundle_document
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (bundle_version_id) DO NOTHING
                    """,
                    (*row[:8], _json_parameter(row[8]), _json_parameter(row[9])),
                )
                stored = self._load_by_id(connection, value.bundle_version_id)
                if stored is None:
                    raise RuntimeError("valuation input bundle insert was not observable")
                if bundle_content_hash(stored) != bundle_content_hash(value):
                    raise ValuationImprovementInputConflict(
                        f"immutable valuation input bundle conflict: {value.bundle_version_id}"
                    )
                for dataset_version_id in value.dataset_version_ids:
                    connection.execute(
                        """
                        INSERT INTO research.valuation_input_bundle_datasets (
                            bundle_version_id, dataset_version_id
                        ) VALUES (%s, %s)
                        ON CONFLICT (bundle_version_id, dataset_version_id) DO NOTHING
                        """,
                        (value.bundle_version_id, dataset_version_id),
                    )
                return stored
        except psycopg.OperationalError as error:
            raise self._unavailable() from error
        except psycopg.errors.UniqueViolation as error:
            raise ValuationImprovementInputConflict(
                f"immutable valuation input bundle conflict: {value.bundle_version_id}"
            ) from error

    def load(
        self,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        if not isinstance(query, ValuationImprovementInputRequest):
            raise TypeError("query must be a ValuationImprovementInputRequest")
        try:
            with self._connection_factory() as connection, connection.transaction():
                connection.execute("SET TRANSACTION READ ONLY")
                return self._load(connection, query)
        except psycopg.OperationalError as error:
            raise self._unavailable() from error

    @staticmethod
    def _request_for(
        value: ValuationImprovementInputBundle,
    ) -> ValuationImprovementInputRequest:
        return ValuationImprovementInputRequest(
            security_id=value.security_id,
            decision_time=value.decision_time,
            data_mode=value.data_mode,
            trust_state=value.trust_state,
            bundle_version_id=value.bundle_version_id,
        )

    @staticmethod
    def _select() -> str:
        return """
            SELECT bundle_version_id, security_id, decision_time, content_hash,
                   data_mode, trust_state, latest_source_available_at,
                   document_schema_version, dataset_version_ids, bundle_document
            FROM research.valuation_input_bundles
        """

    def _load(
        self,
        connection: Connection,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        row = connection.execute(
            self._select()
            + """
            WHERE security_id = %s AND decision_time = %s
              AND data_mode = %s AND trust_state = %s
              AND bundle_version_id = %s
            """,
            (
                query.security_id,
                query.decision_time,
                query.data_mode.value,
                query.trust_state.value,
                query.bundle_version_id,
            ),
        ).fetchone()
        return None if row is None else self.from_row(row)

    def _load_by_id(
        self,
        connection: Connection,
        bundle_version_id: str,
    ) -> ValuationImprovementInputBundle | None:
        row = connection.execute(
            self._select() + " WHERE bundle_version_id = %s",
            (bundle_version_id,),
        ).fetchone()
        return None if row is None else self.from_row(row)

    @staticmethod
    def to_row(value: ValuationImprovementInputBundle) -> tuple[object, ...]:
        return (
            value.bundle_version_id,
            value.security_id,
            value.decision_time,
            bundle_content_hash(value),
            value.data_mode.value,
            value.trust_state.value,
            value.latest_source_available_at,
            value.document_schema_version,
            list(value.dataset_version_ids),
            bundle_document(value),
        )

    @staticmethod
    def from_row(row: Sequence[object]) -> ValuationImprovementInputBundle:
        if len(row) != 10:
            raise ValueError("stored valuation input bundle row has an invalid shape")
        value = bundle_from_document(row[9])
        expected = (
            value.bundle_version_id,
            value.security_id,
            value.decision_time,
            value.data_mode.value,
            value.trust_state.value,
            value.latest_source_available_at,
            value.document_schema_version,
            tuple(value.dataset_version_ids),
        )
        stored = (
            str(row[0]),
            str(row[1]),
            cast(datetime, row[2]),
            str(row[4]),
            str(row[5]),
            cast(datetime, row[6]),
            str(row[7]),
            tuple(str(item) for item in _array(row[8], "dataset_version_ids")),
        )
        if stored != expected:
            raise ValueError("stored valuation input bundle columns do not match document")
        if str(row[3]) != bundle_content_hash(value):
            raise ValueError("stored valuation input bundle hash mismatch")
        return value

    @staticmethod
    def _unavailable() -> ValuationImprovementInputUnavailable:
        return ValuationImprovementInputUnavailable(
            "PostgreSQL frozen valuation input store is unavailable"
        )


__all__ = [
    "PostgresValuationImprovementInputRepository",
    "bundle_content_hash",
    "bundle_document",
    "bundle_from_document",
]
