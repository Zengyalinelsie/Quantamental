"""Fail-closed bridge from exact PIT analysis to one immutable InvestmentView."""

from __future__ import annotations

from dataclasses import dataclass, replace

from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerService,
)
from a_share_platform.application.valuation_improvement import (
    ValuationImprovementAnalysis,
    ValuationImprovementAnalysisStatus,
    ValuationImprovementComponentStatus,
    ValuationImprovementOrchestrationService,
)
from a_share_platform.domain.expected_return import (
    ExpectedReturnCompileRequest,
    ExpectedReturnCompilerV0,
)
from a_share_platform.domain.investment_view import (
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage
from a_share_platform.ports.valuation_inputs import ValuationImprovementInputRequest


@dataclass(frozen=True)
class InvestmentViewCompilation:
    analysis: ValuationImprovementAnalysis
    blockers: tuple[str, ...]
    view: InvestmentView | None
    writes_performed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.analysis, ValuationImprovementAnalysis):
            raise TypeError("analysis must be a ValuationImprovementAnalysis")
        blockers = tuple(dict.fromkeys(self.blockers))
        if any(not isinstance(value, str) or not value.strip() for value in blockers):
            raise ValueError("blockers must contain non-empty text")
        object.__setattr__(self, "blockers", blockers)
        if self.view is not None and not isinstance(self.view, InvestmentView):
            raise TypeError("view must be an InvestmentView or None")
        if bool(blockers) == (self.view is not None):
            raise ValueError("a compilation must contain either blockers or one view")
        if type(self.writes_performed) is not bool:
            raise TypeError("writes_performed must be a boolean")
        if self.writes_performed and self.view is None:
            raise ValueError("a write cannot occur without a compiled view")

    @property
    def qualified(self) -> bool:
        return self.view is not None and not self.blockers


class InvestmentViewCompilationService:
    """Compile only from strict PIT analysis and exact frozen model output.

    This service validates evidence binding; it does not estimate expected-return
    contributions, percentiles, confidence, or residual values itself.
    """

    def __init__(
        self,
        analysis_service: ValuationImprovementOrchestrationService,
        compiler: ExpectedReturnCompilerV0,
        ledger: ExpectedReturnLedgerService,
    ) -> None:
        if not isinstance(
            analysis_service,
            ValuationImprovementOrchestrationService,
        ):
            raise TypeError(
                "analysis_service must be a ValuationImprovementOrchestrationService"
            )
        if not isinstance(compiler, ExpectedReturnCompilerV0):
            raise TypeError("compiler must be an ExpectedReturnCompilerV0")
        if not isinstance(ledger, ExpectedReturnLedgerService):
            raise TypeError("ledger must be an ExpectedReturnLedgerService")
        self._analysis_service = analysis_service
        self._compiler = compiler
        self._ledger = ledger

    def evaluate(
        self,
        valuation_request: ValuationImprovementInputRequest,
        expected_return_request: ExpectedReturnCompileRequest,
    ) -> InvestmentViewCompilation:
        return self._compile(valuation_request, expected_return_request)

    def ensure(
        self,
        valuation_request: ValuationImprovementInputRequest,
        expected_return_request: ExpectedReturnCompileRequest,
    ) -> InvestmentViewCompilation:
        compilation = self._compile(valuation_request, expected_return_request)
        if compilation.view is None:
            return compilation
        existing = self._ledger.get_view(compilation.view.view_id)
        stored = self._ledger.record_view(compilation.view)
        return replace(
            compilation,
            view=stored,
            writes_performed=existing is None,
        )

    def _compile(
        self,
        valuation_request: ValuationImprovementInputRequest,
        expected_return_request: ExpectedReturnCompileRequest,
    ) -> InvestmentViewCompilation:
        if not isinstance(valuation_request, ValuationImprovementInputRequest):
            raise TypeError("valuation_request must be a ValuationImprovementInputRequest")
        if not isinstance(expected_return_request, ExpectedReturnCompileRequest):
            raise TypeError("expected_return_request must be an ExpectedReturnCompileRequest")
        analysis = self._analysis_service.evaluate(valuation_request)
        blockers = self._blockers(
            valuation_request,
            expected_return_request,
            analysis,
        )
        if blockers:
            return InvestmentViewCompilation(
                analysis=analysis,
                blockers=blockers,
                view=None,
                writes_performed=False,
            )
        return InvestmentViewCompilation(
            analysis=analysis,
            blockers=(),
            view=self._compiler.compile(expected_return_request),
            writes_performed=False,
        )

    @staticmethod
    def _blockers(
        valuation_request: ValuationImprovementInputRequest,
        expected_return_request: ExpectedReturnCompileRequest,
        analysis: ValuationImprovementAnalysis,
    ) -> tuple[str, ...]:
        blockers: list[str] = []
        context = expected_return_request.run_context
        if context.data_mode is not DataMode.STRICT_HISTORICAL:
            blockers.append(
                "InvestmentView persistence requires strict_historical model output"
            )
        if context.deployment_stage is not DeploymentStage.RESEARCH:
            blockers.append("InvestmentView compilation requires research deployment")
        if expected_return_request.trust_state is not DataTrustState.PIT_VERIFIED:
            blockers.append("InvestmentView persistence requires pit_verified model output")
        axes = (
            (
                "security_id",
                expected_return_request.security_id,
                valuation_request.security_id,
            ),
            (
                "decision_time",
                expected_return_request.decision_time,
                valuation_request.decision_time,
            ),
            (
                "data_mode",
                context.data_mode,
                valuation_request.data_mode,
            ),
            (
                "trust_state",
                expected_return_request.trust_state,
                valuation_request.trust_state,
            ),
        )
        blockers.extend(
            f"Expected Return {name} does not match valuation input request"
            for name, expected, actual in axes
            if expected != actual
        )

        if analysis.status is not ValuationImprovementAnalysisStatus.QUANTIFIED:
            blockers.append(
                f"valuation/improvement analysis is {analysis.status.value}, not quantified"
            )
        if not analysis.historical_eligible:
            blockers.append("valuation/improvement analysis is not strict PIT eligible")
        if analysis.valuation_status is not ValuationImprovementComponentStatus.QUANTIFIED:
            blockers.append("valuation analysis is not quantified")
        if analysis.improvement_status is not ValuationImprovementComponentStatus.QUANTIFIED:
            blockers.append("revision analysis is not quantified")
        if analysis.scenario_status is not ValuationImprovementComponentStatus.QUANTIFIED:
            blockers.append("scenario analysis is not quantified")
        if not analysis.input_dataset_version_ids:
            blockers.append("frozen valuation/improvement input bundle is unavailable")
        missing_datasets = set(analysis.input_dataset_version_ids) - set(
            expected_return_request.dataset_version_ids
        )
        if missing_datasets:
            blockers.append(
                "Expected Return DatasetVersion lineage omits frozen inputs: "
                + ", ".join(sorted(missing_datasets))
            )
        if (
            analysis.latest_input_available_at is None
            or expected_return_request.latest_input_available_at
            < analysis.latest_input_available_at
        ):
            blockers.append(
                "Expected Return availability predates valuation/improvement evidence"
            )

        components = {
            value.name: value for value in expected_return_request.components
        }
        for name in ("quality", "valuation", "revision"):
            if components[name].status is not InvestmentComponentStatus.QUANTIFIED:
                blockers.append(f"{name} InvestmentView component is not quantified")

        valuation = analysis.valuation_result
        improvement = analysis.improvement_result
        scenario = analysis.scenario_result
        if valuation is not None:
            InvestmentViewCompilationService._require_evidence(
                blockers,
                components["valuation"],
                (analysis.bundle_version_id, valuation.definition_hash),
                "valuation evidence",
            )
        if improvement is not None:
            InvestmentViewCompilationService._require_evidence(
                blockers,
                components["revision"],
                (analysis.bundle_version_id, improvement.definition_hash),
                "revision evidence",
            )
        if scenario is not None:
            missing_residual = {
                analysis.bundle_version_id,
                scenario.definition_hash,
            } - set(expected_return_request.residual.evidence_ids)
            if missing_residual:
                blockers.append(
                    "residual evidence omits frozen scenario binding: "
                    + ", ".join(sorted(missing_residual))
                )
        return tuple(dict.fromkeys(blockers))

    @staticmethod
    def _require_evidence(
        blockers: list[str],
        component: InvestmentComponent,
        required: tuple[str, ...],
        label: str,
    ) -> None:
        missing = set(required) - set(component.evidence_ids)
        if missing:
            blockers.append(
                f"{label} omits frozen analysis binding: "
                + ", ".join(sorted(missing))
            )


__all__ = [
    "InvestmentViewCompilation",
    "InvestmentViewCompilationService",
]
