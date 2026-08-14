import unittest
from dataclasses import replace
from decimal import Decimal

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
)
from a_share_platform.adapters.memory.valuation_inputs import (
    MemoryValuationImprovementInputSource,
    UnavailableValuationImprovementInputSource,
)
from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerService,
)
from a_share_platform.application.investment_view_compilation import (
    InvestmentViewCompilationService,
)
from a_share_platform.application.valuation_improvement import (
    ValuationImprovementOrchestrationService,
)
from a_share_platform.domain.expected_return import (
    ExpectedReturnCompilerV0,
    ExpectedReturnResidual,
)
from a_share_platform.domain.investment_view import (
    InvestmentComponent,
    InvestmentComponentStatus,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode, DeploymentStage, RunContext
from tests.test_expected_return_compiler import component
from tests.test_expected_return_compiler import request as expected_request
from tests.test_valuation_improvement_service import (
    AVAILABLE_AT,
    DATASET_IDS,
    bundle,
    scenario_definition,
)
from tests.test_valuation_improvement_service import request as valuation_request


def strict_inputs():  # type: ignore[no-untyped-def]
    frozen = bundle(
        data_mode=DataMode.STRICT_HISTORICAL,
        trust_state=DataTrustState.PIT_VERIFIED,
    )
    valuation = valuation_request(
        data_mode=DataMode.STRICT_HISTORICAL,
        trust_state=DataTrustState.PIT_VERIFIED,
    )
    analysis_service = ValuationImprovementOrchestrationService(
        MemoryValuationImprovementInputSource((frozen,)),
        scenario_definition(),
    )
    analysis = analysis_service.evaluate(valuation)
    assert analysis.valuation_result is not None
    assert analysis.improvement_result is not None
    assert analysis.scenario_result is not None
    expected = replace(
        expected_request(),
        security_id=frozen.security_id,
        decision_time=frozen.decision_time,
        components=(
            InvestmentComponent(
                name="quality",
                status=InvestmentComponentStatus.QUANTIFIED,
                expected_return_contribution=Decimal("0.018"),
                evidence_ids=("feature:quality:pit:v1",),
            ),
            InvestmentComponent(
                name="valuation",
                status=InvestmentComponentStatus.QUANTIFIED,
                expected_return_contribution=Decimal("0.021"),
                evidence_ids=(
                    frozen.bundle_version_id,
                    analysis.valuation_result.definition_hash,
                ),
            ),
            InvestmentComponent(
                name="revision",
                status=InvestmentComponentStatus.QUANTIFIED,
                expected_return_contribution=Decimal("0.014"),
                evidence_ids=(
                    frozen.bundle_version_id,
                    analysis.improvement_result.definition_hash,
                ),
            ),
            component(
                "event",
                InvestmentComponentStatus.UNAVAILABLE,
                reason="P8 event model is unavailable",
            ),
        ),
        residual=ExpectedReturnResidual(
            value=Decimal("0.006"),
            reason="Approved V0 residual remains explicit.",
            evidence_ids=(
                frozen.bundle_version_id,
                analysis.scenario_result.definition_hash,
            ),
        ),
        dataset_version_ids=(*DATASET_IDS, "dataset:quality:pit:v1"),
        feature_version_ids=(
            "feature:quality:pit:v1",
            "feature:valuation-expectation-gap:v0",
            "feature:fundamental-improvement:v0",
        ),
        model_version_id="model:expected-return:v0",
        run_id="run:expected-return:pit:001",
        run_context=RunContext(
            DataMode.STRICT_HISTORICAL,
            DeploymentStage.RESEARCH,
        ),
        trust_state=DataTrustState.PIT_VERIFIED,
        latest_input_available_at=AVAILABLE_AT,
    )
    return analysis_service, valuation, expected


def service(
    analysis_service: ValuationImprovementOrchestrationService,
) -> tuple[InvestmentViewCompilationService, InMemoryExpectedReturnLedgerRepository]:
    repository = InMemoryExpectedReturnLedgerRepository()
    return (
        InvestmentViewCompilationService(
            analysis_service,
            ExpectedReturnCompilerV0(),
            ExpectedReturnLedgerService(repository),
        ),
        repository,
    )


class InvestmentViewCompilationServiceTest(unittest.TestCase):
    def test_exact_pit_analysis_compiles_then_idempotently_persists_one_view(self) -> None:
        analysis_service, valuation, expected = strict_inputs()
        use_case, repository = service(analysis_service)

        preview = use_case.evaluate(valuation, expected)
        self.assertTrue(preview.qualified)
        self.assertEqual(preview.blockers, ())
        self.assertIsNotNone(preview.view)
        self.assertFalse(preview.writes_performed)
        self.assertEqual(repository.list_views(), ())

        first = use_case.ensure(valuation, expected)
        second = use_case.ensure(valuation, expected)
        self.assertTrue(first.writes_performed)
        self.assertFalse(second.writes_performed)
        self.assertEqual(first.view, second.view)
        self.assertEqual(repository.list_views(), (first.view,))

    def test_current_or_missing_pit_bundle_is_explained_and_never_written(self) -> None:
        current_analysis = ValuationImprovementOrchestrationService(
            MemoryValuationImprovementInputSource((bundle(),)),
            scenario_definition(),
        )
        use_case, repository = service(current_analysis)
        current = use_case.ensure(valuation_request(), expected_request())

        self.assertFalse(current.qualified)
        self.assertTrue(any("strict_historical" in value for value in current.blockers))
        self.assertFalse(current.writes_performed)

        unavailable, missing_repository = service(
            ValuationImprovementOrchestrationService(
                UnavailableValuationImprovementInputSource(),
                scenario_definition(),
            )
        )
        _, valuation, expected = strict_inputs()
        missing = unavailable.ensure(valuation, expected)
        self.assertFalse(missing.qualified)
        self.assertTrue(any("frozen" in value for value in missing.blockers))
        self.assertEqual(repository.list_views(), ())
        self.assertEqual(missing_repository.list_views(), ())

    def test_axis_lineage_and_exact_analysis_evidence_must_close(self) -> None:
        analysis_service, valuation, expected = strict_inputs()
        use_case, repository = service(analysis_service)
        valuation_component = expected.components[1]
        revision_component = expected.components[2]
        broken = replace(
            expected,
            dataset_version_ids=("dataset:quality:pit:v1",),
            components=(
                expected.components[0],
                replace(valuation_component, evidence_ids=("evidence:other",)),
                replace(revision_component, evidence_ids=("evidence:other",)),
                expected.components[3],
            ),
            latest_input_available_at=AVAILABLE_AT.replace(year=2024),
        )

        result = use_case.ensure(valuation, broken)

        self.assertFalse(result.qualified)
        self.assertTrue(any("DatasetVersion" in value for value in result.blockers))
        self.assertTrue(any("valuation evidence" in value for value in result.blockers))
        self.assertTrue(any("revision evidence" in value for value in result.blockers))
        self.assertTrue(any("availability" in value for value in result.blockers))
        self.assertEqual(repository.list_views(), ())

    def test_partial_analysis_and_non_research_stage_fail_closed(self) -> None:
        partial_bundle = bundle(
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
            bull_available=False,
        )
        partial_service = ValuationImprovementOrchestrationService(
            MemoryValuationImprovementInputSource((partial_bundle,)),
            scenario_definition(),
        )
        _, valuation, expected = strict_inputs()
        expected = replace(
            expected,
            run_context=RunContext(
                DataMode.CURRENT_RESEARCH,
                DeploymentStage.SHADOW,
            ),
            trust_state=DataTrustState.NORMALIZED_CURRENT,
        )
        use_case, repository = service(partial_service)

        result = use_case.ensure(valuation, expected)

        self.assertFalse(result.qualified)
        self.assertTrue(any("research deployment" in value for value in result.blockers))
        self.assertTrue(any("scenario" in value for value in result.blockers))
        self.assertEqual(repository.list_views(), ())


if __name__ == "__main__":
    unittest.main()
