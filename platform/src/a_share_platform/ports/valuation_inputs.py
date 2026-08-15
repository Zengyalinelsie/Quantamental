"""Provider-neutral frozen input contracts for valuation and improvement runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, TypeAlias

from a_share_platform.domain.fundamental_improvement import (
    FundamentalImprovementExposures,
    FundamentalImprovementInput,
)
from a_share_platform.domain.industry_templates import IndustryTemplateId
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import (
    ValuationExpectationRangeInput,
    ValuationExposures,
    ValuationMetricInput,
)
from a_share_platform.domain.valuation_models import (
    AnalystRevisionInput,
    FundamentalAnchorInput,
    IndustryValuationPolicy,
    RelativeReferenceKind,
    RelativeValuationReferenceInput,
    UnavailableAnalystRevisionInput,
    UnavailableFundamentalAnchorInput,
)
from a_share_platform.domain.valuation_scenarios import ValuationScenarioInput

VALUATION_INPUT_BUNDLE_V1 = "valuation-input-bundle:v1"
VALUATION_INPUT_BUNDLE_V2 = "valuation-input-bundle:v2"


class _DatasetVersionLineage(Protocol):
    @property
    def dataset_version_ids(self) -> tuple[str, ...]: ...

FrozenValuationImprovementInput: TypeAlias = (
    ValuationMetricInput
    | ValuationExpectationRangeInput
    | FundamentalImprovementInput
    | ValuationScenarioInput
    | RelativeValuationReferenceInput
    | FundamentalAnchorInput
    | UnavailableFundamentalAnchorInput
    | AnalystRevisionInput
    | UnavailableAnalystRevisionInput
)


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


@dataclass(frozen=True)
class ValuationImprovementInputRequest:
    security_id: str
    decision_time: datetime
    data_mode: DataMode
    trust_state: DataTrustState
    bundle_version_id: str

    def __post_init__(self) -> None:
        _text(self.security_id, "security_id")
        _aware(self.decision_time, "decision_time")
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw trust cannot be requested for valuation/improvement")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical request requires pit_verified trust")
        _text(self.bundle_version_id, "bundle_version_id")
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)

    @property
    def frozen_key(self) -> tuple[str, datetime, DataMode, DataTrustState, str]:
        return (
            self.security_id,
            self.decision_time,
            self.data_mode,
            self.trust_state,
            self.bundle_version_id,
        )


@dataclass(frozen=True)
class ValuationModelSuiteInputs:
    """All provider-neutral V0 model inputs frozen inside one bundle aggregate."""

    industry_policy: IndustryValuationPolicy
    relative_references: tuple[RelativeValuationReferenceInput, ...]
    fundamental_anchor_input: FundamentalAnchorInput | UnavailableFundamentalAnchorInput
    analyst_revision_input: AnalystRevisionInput | UnavailableAnalystRevisionInput
    relative_model_version: str
    fundamental_anchor_model_version: str
    implied_expectation_model_version: str
    analyst_revision_model_version: str
    bundle_compiler_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.industry_policy, IndustryValuationPolicy):
            raise TypeError("industry_policy must be IndustryValuationPolicy")
        for name in (
            "relative_model_version",
            "fundamental_anchor_model_version",
            "implied_expectation_model_version",
            "analyst_revision_model_version",
            "bundle_compiler_version",
        ):
            _text(getattr(self, name), name)
        references = tuple(self.relative_references)
        if any(not isinstance(value, RelativeValuationReferenceInput) for value in references):
            raise TypeError("relative_references contain an invalid value")
        expected_keys = {
            (metric, kind)
            for metric in self.industry_policy.relative_metrics
            for kind in RelativeReferenceKind
        }
        actual_keys = {(value.metric, value.reference_kind) for value in references}
        if len(actual_keys) != len(references):
            raise ValueError("duplicate relative valuation reference")
        if actual_keys != expected_keys:
            raise ValueError(
                "relative references must cover every policy metric and reference kind"
            )
        if not isinstance(
            self.fundamental_anchor_input,
            (FundamentalAnchorInput, UnavailableFundamentalAnchorInput),
        ):
            raise TypeError("fundamental_anchor_input has an invalid value")
        if (
            self.fundamental_anchor_input.industry_template_id
            is not self.industry_policy.industry_template_id
        ):
            raise ValueError("anchor input does not match the frozen industry policy")
        if not isinstance(
            self.analyst_revision_input,
            (AnalystRevisionInput, UnavailableAnalystRevisionInput),
        ):
            raise TypeError("analyst_revision_input has an invalid value")
        if (
            self.analyst_revision_input.expectation_metric
            is not self.industry_policy.expectation_metric
        ):
            raise ValueError("analyst expectation metric does not match industry policy")
        object.__setattr__(self, "relative_references", references)


@dataclass(frozen=True)
class ValuationImprovementInputBundle:
    bundle_version_id: str
    security_id: str
    decision_time: datetime
    latest_source_available_at: datetime
    data_mode: DataMode
    trust_state: DataTrustState
    dataset_version_ids: tuple[str, ...]
    industry_template_id: IndustryTemplateId
    valuation_formula_version: str
    improvement_formula_version: str
    scenario_method_id: str
    scenario_method_version: str
    valuation_metric_inputs: tuple[ValuationMetricInput, ...]
    market_implied: ValuationExpectationRangeInput | None
    fundamental_anchor: ValuationExpectationRangeInput | None
    valuation_exposures: ValuationExposures
    currency: str
    comparable_set_version_id: str
    improvement_inputs: tuple[FundamentalImprovementInput, ...]
    improvement_exposures: FundamentalImprovementExposures
    scenario_inputs: tuple[ValuationScenarioInput, ...]
    document_schema_version: str = VALUATION_INPUT_BUNDLE_V1
    valuation_model_suite_inputs: ValuationModelSuiteInputs | None = None

    def __post_init__(self) -> None:
        for name in (
            "bundle_version_id",
            "security_id",
            "valuation_formula_version",
            "improvement_formula_version",
            "scenario_method_id",
            "scenario_method_version",
            "comparable_set_version_id",
            "document_schema_version",
        ):
            _text(getattr(self, name), name)
        decision_time = _aware(self.decision_time, "decision_time")
        latest_available = _aware(
            self.latest_source_available_at,
            "latest_source_available_at",
        )
        if latest_available > decision_time:
            raise ValueError("latest_source_available_at cannot exceed decision_time")
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("raw inputs cannot enter a frozen valuation/improvement bundle")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical bundle requires pit_verified trust")
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "trust_state", trust)
        if self.document_schema_version not in {
            VALUATION_INPUT_BUNDLE_V1,
            VALUATION_INPUT_BUNDLE_V2,
        }:
            raise ValueError(
                f"unknown valuation input bundle schema: {self.document_schema_version}"
            )
        if self.document_schema_version == VALUATION_INPUT_BUNDLE_V1:
            if self.valuation_model_suite_inputs is not None:
                raise ValueError("legacy v1 bundle cannot carry valuation model suite inputs")
            if not isinstance(
                self.market_implied,
                ValuationExpectationRangeInput,
            ) or not isinstance(
                self.fundamental_anchor,
                ValuationExpectationRangeInput,
            ):
                raise ValueError("legacy v1 bundle requires precomputed expectation inputs")
        elif not isinstance(self.valuation_model_suite_inputs, ValuationModelSuiteInputs):
            raise ValueError("valuation input bundle v2 requires model suite inputs")
        elif self.market_implied is not None or self.fundamental_anchor is not None:
            raise ValueError("valuation input bundle v2 cannot freeze precomputed expectations")
        object.__setattr__(
            self,
            "industry_template_id",
            IndustryTemplateId(self.industry_template_id),
        )
        if not isinstance(self.currency, str) or re.fullmatch(r"[A-Z]{3}", self.currency) is None:
            raise ValueError("bundle currency must be a three-letter uppercase code")
        if not isinstance(self.valuation_exposures, ValuationExposures):
            raise TypeError("valuation_exposures must be ValuationExposures")
        if not isinstance(self.improvement_exposures, FundamentalImprovementExposures):
            raise TypeError("improvement_exposures must be FundamentalImprovementExposures")
        valuation_values = tuple(self.valuation_metric_inputs)
        improvement_values = tuple(self.improvement_inputs)
        scenario_values = tuple(self.scenario_inputs)
        if any(not isinstance(value, ValuationMetricInput) for value in valuation_values):
            raise TypeError("valuation_metric_inputs contain an invalid value")
        if not improvement_values or any(
            not isinstance(value, FundamentalImprovementInput) for value in improvement_values
        ):
            raise ValueError("improvement_inputs must contain at least one valid input")
        if any(not isinstance(value, ValuationScenarioInput) for value in scenario_values):
            raise TypeError("scenario_inputs contain an invalid value")
        self._require_unique_keys(
            tuple(value.metric.value for value in valuation_values),
            "valuation metric",
        )
        self._require_unique_keys(
            tuple(value.metric.value for value in improvement_values),
            "improvement metric",
        )
        self._require_unique_keys(
            tuple(value.scenario.value for value in scenario_values),
            "valuation scenario",
        )
        if {value.scenario.value for value in scenario_values} != {"bear", "base", "bull"}:
            raise ValueError("scenario_inputs require base, bull, and bear")
        object.__setattr__(self, "valuation_metric_inputs", valuation_values)
        object.__setattr__(self, "improvement_inputs", improvement_values)
        object.__setattr__(self, "scenario_inputs", scenario_values)

        expectation_evidence: tuple[ValuationExpectationRangeInput, ...] = (
            ()
            if self.market_implied is None or self.fundamental_anchor is None
            else (self.market_implied, self.fundamental_anchor)
        )
        base_evidence: tuple[FrozenValuationImprovementInput, ...] = (
            *valuation_values,
            *expectation_evidence,
            *improvement_values,
            *scenario_values,
        )
        suite = self.valuation_model_suite_inputs
        suite_evidence: tuple[FrozenValuationImprovementInput, ...] = ()
        suite_provenances: tuple[_DatasetVersionLineage, ...] = ()
        if suite is not None:
            if suite.industry_policy.industry_template_id is not self.industry_template_id:
                raise ValueError("valuation model suite industry policy does not match bundle")
            comparable_ids = {
                value.comparable_set_version_id for value in suite.relative_references
            }
            if comparable_ids != {self.comparable_set_version_id}:
                raise ValueError("relative references do not match bundle comparable set")
            if suite.fundamental_anchor_input.currency != self.currency:
                raise ValueError("fundamental anchor currency does not match bundle")
            suite_evidence = (
                *suite.relative_references,
                suite.fundamental_anchor_input,
                suite.analyst_revision_input,
            )
            suite_provenances = (
                *(value.provenance for value in suite.relative_references),
                *suite.fundamental_anchor_input.provenances,
                *(
                    suite.analyst_revision_input.provenances
                    if isinstance(
                        suite.analyst_revision_input,
                        UnavailableAnalystRevisionInput,
                    )
                    else (
                        suite.analyst_revision_input.current_provenance,
                        suite.analyst_revision_input.prior_provenance,
                    )
                ),
            )
        evidence = (*base_evidence, *suite_evidence)
        for value in evidence:
            if value.data_mode is not mode:
                raise ValueError("bundle input data_mode does not match bundle data_mode")
            if value.trust_state is not trust:
                raise ValueError("bundle input trust_state does not match bundle trust_state")
            if value.decision_time != decision_time:
                raise ValueError("bundle input decision_time does not match bundle cutoff")
            if value.latest_source_available_at is None and not isinstance(
                value,
                UnavailableAnalystRevisionInput,
            ):
                raise ValueError("frozen bundle inputs require latest_source_available_at")
        availability_times = tuple(value.latest_source_available_at for value in evidence)
        actual_latest = max(value for value in availability_times if value is not None)
        if actual_latest != latest_available:
            raise ValueError(
                "latest_source_available_at must equal the latest frozen input availability"
            )
        declared_datasets = tuple(sorted(self.dataset_version_ids))
        if not declared_datasets or any(not value.strip() for value in declared_datasets):
            raise ValueError("dataset_version_ids must contain non-empty versions")
        if len(declared_datasets) != len(set(declared_datasets)):
            raise ValueError("dataset_version_ids must be unique")
        base_provenances: tuple[_DatasetVersionLineage, ...] = (
            *(value.provenance for value in valuation_values),
            *(value.provenance for value in expectation_evidence),
            *(value.provenance for value in improvement_values),
            *(value.provenance for value in scenario_values),
        )
        actual_datasets = tuple(
            sorted(
                {
                    dataset_id
                    for provenance in (*base_provenances, *suite_provenances)
                    for dataset_id in provenance.dataset_version_ids
                }
            )
        )
        if declared_datasets != actual_datasets:
            raise ValueError("dataset_version_ids do not match frozen input lineage")
        object.__setattr__(self, "dataset_version_ids", declared_datasets)

    @staticmethod
    def _require_unique_keys(values: tuple[str, ...], label: str) -> None:
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate {label} input")

    @property
    def frozen_key(self) -> tuple[str, datetime, DataMode, DataTrustState, str]:
        return (
            self.security_id,
            self.decision_time,
            self.data_mode,
            self.trust_state,
            self.bundle_version_id,
        )


class ValuationImprovementInputSource(Protocol):
    def load(
        self,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None: ...


class ValuationImprovementInputConflict(RuntimeError):
    """An immutable frozen bundle identifier or natural key was reused."""


class ValuationImprovementInputUnavailable(RuntimeError):
    """The configured durable frozen-input store cannot be reached."""


class ValuationImprovementInputRepository(ValuationImprovementInputSource, Protocol):
    def append(
        self,
        value: ValuationImprovementInputBundle,
    ) -> ValuationImprovementInputBundle: ...


__all__ = [
    "VALUATION_INPUT_BUNDLE_V1",
    "VALUATION_INPUT_BUNDLE_V2",
    "ValuationImprovementInputBundle",
    "ValuationImprovementInputConflict",
    "ValuationImprovementInputRepository",
    "ValuationImprovementInputRequest",
    "ValuationImprovementInputSource",
    "ValuationImprovementInputUnavailable",
    "ValuationModelSuiteInputs",
]
