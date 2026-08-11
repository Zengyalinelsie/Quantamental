"""Application orchestration for frozen valuation and improvement inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from a_share_platform.domain.fundamental_improvement import (
    FundamentalImprovementResult,
    ImprovementResultStatus,
    fundamental_improvement_definition_v0,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.valuation_expectation_gap import (
    ValuationExpectationGapResult,
    ValuationResultStatus,
    valuation_expectation_gap_definition_v0,
)
from a_share_platform.domain.valuation_scenarios import (
    ValuationScenarioSensitivityDefinition,
    ValuationScenarioSensitivityResult,
    ValuationScenarioSetStatus,
    ValuationScenarioStatus,
)
from a_share_platform.ports.valuation_inputs import (
    ValuationImprovementInputBundle,
    ValuationImprovementInputRequest,
    ValuationImprovementInputSource,
)


class ValuationImprovementComponentStatus(str, Enum):
    QUANTIFIED = "quantified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ValuationImprovementAnalysisStatus(str, Enum):
    QUANTIFIED = "quantified"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ValuationImprovementScientificStatus(str, Enum):
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True)
class ValuationImprovementAnalysis:
    status: ValuationImprovementAnalysisStatus
    security_id: str
    decision_time: datetime
    latest_input_available_at: datetime | None
    data_mode: DataMode
    trust_state: DataTrustState
    historical_eligible: bool
    bundle_version_id: str
    input_dataset_version_ids: tuple[str, ...]
    valuation_status: ValuationImprovementComponentStatus
    improvement_status: ValuationImprovementComponentStatus
    scenario_status: ValuationImprovementComponentStatus
    valuation_result: ValuationExpectationGapResult | None
    improvement_result: FundamentalImprovementResult | None
    scenario_result: ValuationScenarioSensitivityResult | None
    unavailable_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    scientific_status: ValuationImprovementScientificStatus


class ValuationImprovementOrchestrationService:
    """Execute domain methods only from one exact, frozen provider bundle."""

    def __init__(
        self,
        source: ValuationImprovementInputSource,
        scenario_definition: ValuationScenarioSensitivityDefinition,
    ) -> None:
        if not isinstance(scenario_definition, ValuationScenarioSensitivityDefinition):
            raise TypeError("scenario_definition must be ValuationScenarioSensitivityDefinition")
        self._source = source
        self._scenario_definition = scenario_definition

    def evaluate(
        self,
        request: ValuationImprovementInputRequest,
    ) -> ValuationImprovementAnalysis:
        if not isinstance(request, ValuationImprovementInputRequest):
            raise TypeError("request must be ValuationImprovementInputRequest")
        bundle = self._source.load(request)
        if bundle is None:
            warnings: tuple[str, ...] = (
                ("current_research orchestration is current-only, not historical evidence",)
                if request.data_mode is DataMode.CURRENT_RESEARCH
                else ()
            )
            return ValuationImprovementAnalysis(
                status=ValuationImprovementAnalysisStatus.UNAVAILABLE,
                security_id=request.security_id,
                decision_time=request.decision_time,
                latest_input_available_at=None,
                data_mode=request.data_mode,
                trust_state=request.trust_state,
                historical_eligible=False,
                bundle_version_id=request.bundle_version_id,
                input_dataset_version_ids=(),
                valuation_status=ValuationImprovementComponentStatus.UNAVAILABLE,
                improvement_status=ValuationImprovementComponentStatus.UNAVAILABLE,
                scenario_status=ValuationImprovementComponentStatus.UNAVAILABLE,
                valuation_result=None,
                improvement_result=None,
                scenario_result=None,
                unavailable_reasons=("frozen valuation/improvement input bundle is unavailable",),
                warnings=warnings,
                scientific_status=ValuationImprovementScientificStatus.NOT_EVALUATED,
            )
        self._validate_response(request, bundle)

        valuation_definition = valuation_expectation_gap_definition_v0(bundle.industry_template_id)
        improvement_definition = fundamental_improvement_definition_v0()
        self._validate_definition_versions(
            bundle,
            valuation_formula_version=valuation_definition.formula_version,
            improvement_formula_version=improvement_definition.formula_version,
        )
        valuation_result = valuation_definition.calculate(
            {value.metric: value for value in bundle.valuation_metric_inputs},
            market_implied=bundle.market_implied,
            fundamental_anchor=bundle.fundamental_anchor,
            exposures=bundle.valuation_exposures,
            data_mode=request.data_mode,
            currency=bundle.currency,
            comparable_set_version_id=bundle.comparable_set_version_id,
        )
        improvement_result = improvement_definition.calculate(
            {value.metric: value for value in bundle.improvement_inputs},
            exposures=bundle.improvement_exposures,
            data_mode=request.data_mode,
        )
        scenario_result = self._scenario_definition.calculate(
            bundle.scenario_inputs,
            data_mode=request.data_mode,
        )

        valuation_status = self._valuation_status(valuation_result.status)
        improvement_status = self._improvement_status(improvement_result.status)
        scenario_status = self._scenario_status(scenario_result.status)
        component_statuses = (valuation_status, improvement_status, scenario_status)
        if all(
            value is ValuationImprovementComponentStatus.QUANTIFIED for value in component_statuses
        ):
            status = ValuationImprovementAnalysisStatus.QUANTIFIED
        elif all(
            value is ValuationImprovementComponentStatus.UNAVAILABLE for value in component_statuses
        ):
            status = ValuationImprovementAnalysisStatus.UNAVAILABLE
        else:
            status = ValuationImprovementAnalysisStatus.PARTIAL

        unavailable_reasons = tuple(
            dict.fromkeys(
                (
                    *valuation_result.unavailable_reasons,
                    *(
                        f"fundamental improvement metric is unavailable: {metric.value}"
                        for metric in improvement_result.unavailable_metrics
                    ),
                    *(
                        reason
                        for value in scenario_result.scenario_results
                        if value.status is ValuationScenarioStatus.UNAVAILABLE
                        for reason in value.unavailable_reasons
                    ),
                )
            )
        )
        warnings = tuple(
            dict.fromkeys(
                (
                    *valuation_result.warnings,
                    *improvement_result.warnings,
                    *scenario_result.warnings,
                )
            )
        )
        return ValuationImprovementAnalysis(
            status=status,
            security_id=request.security_id,
            decision_time=request.decision_time,
            latest_input_available_at=bundle.latest_source_available_at,
            data_mode=request.data_mode,
            trust_state=request.trust_state,
            historical_eligible=(
                request.data_mode is DataMode.STRICT_HISTORICAL
                and valuation_result.historical_eligible
                and improvement_result.historical_eligible
                and scenario_result.historical_eligible
            ),
            bundle_version_id=bundle.bundle_version_id,
            input_dataset_version_ids=bundle.dataset_version_ids,
            valuation_status=valuation_status,
            improvement_status=improvement_status,
            scenario_status=scenario_status,
            valuation_result=valuation_result,
            improvement_result=improvement_result,
            scenario_result=scenario_result,
            unavailable_reasons=unavailable_reasons,
            warnings=warnings,
            scientific_status=ValuationImprovementScientificStatus.NOT_EVALUATED,
        )

    @staticmethod
    def _validate_response(
        request: ValuationImprovementInputRequest,
        bundle: ValuationImprovementInputBundle,
    ) -> None:
        if not isinstance(bundle, ValuationImprovementInputBundle):
            raise TypeError("input source returned an invalid bundle")
        if bundle.security_id != request.security_id:
            raise ValueError("returned bundle security_id does not match request")
        if bundle.decision_time != request.decision_time:
            raise ValueError("returned bundle decision_time does not match request")
        if bundle.data_mode is not request.data_mode:
            raise PermissionError("returned bundle data_mode does not match request")
        if bundle.trust_state is not request.trust_state:
            raise PermissionError("returned bundle trust_state does not match request")
        if bundle.bundle_version_id != request.bundle_version_id:
            raise ValueError("returned bundle_version_id does not match request")

    def _validate_definition_versions(
        self,
        bundle: ValuationImprovementInputBundle,
        *,
        valuation_formula_version: str,
        improvement_formula_version: str,
    ) -> None:
        if bundle.valuation_formula_version != valuation_formula_version:
            raise ValueError("valuation formula version does not match frozen bundle")
        if bundle.improvement_formula_version != improvement_formula_version:
            raise ValueError("improvement formula version does not match frozen bundle")
        if bundle.scenario_method_id != self._scenario_definition.method_id:
            raise ValueError("scenario method does not match frozen bundle")
        if bundle.scenario_method_version != self._scenario_definition.method_version:
            raise ValueError("scenario method version does not match frozen bundle")

    @staticmethod
    def _valuation_status(
        value: ValuationResultStatus,
    ) -> ValuationImprovementComponentStatus:
        return {
            ValuationResultStatus.QUANTIFIED: ValuationImprovementComponentStatus.QUANTIFIED,
            ValuationResultStatus.PARTIAL: ValuationImprovementComponentStatus.PARTIAL,
            ValuationResultStatus.UNAVAILABLE: ValuationImprovementComponentStatus.UNAVAILABLE,
        }[value]

    @staticmethod
    def _improvement_status(
        value: ImprovementResultStatus,
    ) -> ValuationImprovementComponentStatus:
        return {
            ImprovementResultStatus.QUANTIFIED: ValuationImprovementComponentStatus.QUANTIFIED,
            ImprovementResultStatus.PARTIAL: ValuationImprovementComponentStatus.PARTIAL,
            ImprovementResultStatus.UNAVAILABLE: ValuationImprovementComponentStatus.UNAVAILABLE,
        }[value]

    @staticmethod
    def _scenario_status(
        value: ValuationScenarioSetStatus,
    ) -> ValuationImprovementComponentStatus:
        return {
            ValuationScenarioSetStatus.QUANTIFIED: (ValuationImprovementComponentStatus.QUANTIFIED),
            ValuationScenarioSetStatus.PARTIAL: ValuationImprovementComponentStatus.PARTIAL,
            ValuationScenarioSetStatus.UNAVAILABLE: (
                ValuationImprovementComponentStatus.UNAVAILABLE
            ),
        }[value]


__all__ = [
    "ValuationImprovementAnalysis",
    "ValuationImprovementAnalysisStatus",
    "ValuationImprovementComponentStatus",
    "ValuationImprovementOrchestrationService",
    "ValuationImprovementScientificStatus",
]
