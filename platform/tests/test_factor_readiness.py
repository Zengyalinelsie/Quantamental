import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.backfill import DatasetQualityStatus
from a_share_platform.domain.factor_readiness import (
    FactorDataAvailabilityPolicy,
    FactorDataBinding,
    FactorDataRequirement,
    FactorDataRole,
    FactorStudyPreflight,
    FactorStudySpec,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import (
    DataMode,
    DeploymentStage,
    RunContext,
)

NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)
START = date(2018, 1, 1)
END = date(2025, 12, 31)


def requirements() -> tuple[FactorDataRequirement, ...]:
    return tuple(
        FactorDataRequirement(
            role=role,
            minimum_coverage=Decimal("0.98"),
            threshold_source="p4-study-policy:v1",
            availability_policy=(
                FactorDataAvailabilityPolicy.LABEL_OUTCOME_ONLY
                if role is FactorDataRole.FORWARD_RETURN_LABEL
                else FactorDataAvailabilityPolicy.DECISION_TIME_CUTOFF
            ),
        )
        for role in FactorDataRole
    )


def study_spec(**overrides: object) -> FactorStudySpec:
    values: dict[str, object] = {
        "study_id": "factor-study:quality:csi800:2018-2025:v1",
        "run_context": RunContext(
            DataMode.STRICT_HISTORICAL,
            DeploymentStage.RESEARCH,
        ),
        "universe_version_id": "universe:csi800:history:v1",
        "benchmark_id": "index:000906",
        "start_date": START,
        "end_date": END,
        "decision_time_policy_version": "decision-time:close-plus-disclosure:v1",
        "requirements": requirements(),
        "created_at": NOW,
    }
    values.update(overrides)
    return FactorStudySpec(**values)  # type: ignore[arg-type]


def bindings() -> tuple[FactorDataBinding, ...]:
    return tuple(
        FactorDataBinding(
            role=requirement.role,
            dataset_version_id=f"dataset:{requirement.role.value}:v1",
            trust_state=DataTrustState.PIT_VERIFIED,
            quality_status=DatasetQualityStatus.PASSED,
            coverage_ratio=Decimal(1),
            start_date=START,
            end_date=END,
            availability_policy=requirement.availability_policy,
            availability_enforced=True,
            lineage_complete=True,
            warnings=(),
        )
        for requirement in requirements()
    )


class FactorStudyPreflightTest(unittest.TestCase):
    def test_complete_pit_bindings_are_eligible_for_historical_research(self) -> None:
        result = FactorStudyPreflight().evaluate(study_spec(), bindings())

        self.assertTrue(result.permitted)
        self.assertEqual(result.blockers, ())
        self.assertEqual(result.bound_dataset_version_ids, tuple(sorted(
            binding.dataset_version_id for binding in bindings()
        )))

    def test_current_data_cannot_be_used_as_historical_factor_evidence(self) -> None:
        current = replace(
            bindings()[0],
            trust_state=DataTrustState.NORMALIZED_CURRENT,
        )
        result = FactorStudyPreflight().evaluate(
            study_spec(),
            (current, *bindings()[1:]),
        )

        self.assertFalse(result.permitted)
        self.assertTrue(any("pit_verified" in blocker for blocker in result.blockers))

    def test_missing_or_undercovered_inputs_remain_explicit_blockers(self) -> None:
        available = bindings()
        without_actions = tuple(
            binding
            for binding in available
            if binding.role is not FactorDataRole.CORPORATE_ACTION
        )
        result = FactorStudyPreflight().evaluate(
            study_spec(),
            tuple(
                replace(binding, coverage_ratio=Decimal("0.90"))
                if binding.role is FactorDataRole.SHARE_CAPITAL
                else binding
                for binding in without_actions
            ),
        )

        self.assertFalse(result.permitted)
        self.assertTrue(any("corporate_action" in item for item in result.blockers))
        self.assertTrue(any("share_capital" in item and "coverage" in item for item in result.blockers))

    def test_failed_quality_missing_lineage_and_unenforced_cutoff_fail_closed(self) -> None:
        changed = {
            FactorDataRole.FINANCIAL_FACT: {
                "quality_status": DatasetQualityStatus.FAILED,
            },
            FactorDataRole.HISTORICAL_UNIVERSE: {"lineage_complete": False},
            FactorDataRole.INDUSTRY_CLASSIFICATION: {
                "availability_enforced": False,
            },
        }
        candidates = tuple(
            replace(binding, **changed.get(binding.role, {}))
            for binding in bindings()
        )

        result = FactorStudyPreflight().evaluate(study_spec(), candidates)

        self.assertFalse(result.permitted)
        joined = " | ".join(result.blockers)
        self.assertIn("financial_fact quality", joined)
        self.assertIn("historical_universe lineage", joined)
        self.assertIn("industry_classification availability", joined)

    def test_label_policy_is_separate_from_decision_time_feature_inputs(self) -> None:
        label = next(
            binding
            for binding in bindings()
            if binding.role is FactorDataRole.FORWARD_RETURN_LABEL
        )
        feature = next(
            binding
            for binding in bindings()
            if binding.role is FactorDataRole.FINANCIAL_FACT
        )

        wrong_label = replace(
            label,
            availability_policy=FactorDataAvailabilityPolicy.DECISION_TIME_CUTOFF,
        )
        wrong_feature = replace(
            feature,
            availability_policy=FactorDataAvailabilityPolicy.LABEL_OUTCOME_ONLY,
        )
        candidates = tuple(
            wrong_label
            if binding.role is label.role
            else wrong_feature
            if binding.role is feature.role
            else binding
            for binding in bindings()
        )

        result = FactorStudyPreflight().evaluate(study_spec(), candidates)

        self.assertFalse(result.permitted)
        self.assertTrue(any("forward_return_label availability policy" in item for item in result.blockers))
        self.assertTrue(any("financial_fact availability policy" in item for item in result.blockers))

    def test_current_research_context_is_not_a_p4_historical_gate_pass(self) -> None:
        current_spec = study_spec(
            run_context=RunContext(
                DataMode.CURRENT_RESEARCH,
                DeploymentStage.RESEARCH,
            )
        )

        result = FactorStudyPreflight().evaluate(current_spec, bindings())

        self.assertFalse(result.permitted)
        self.assertTrue(any("strict_historical" in item for item in result.blockers))

    def test_thresholds_require_decimal_values_and_a_named_source(self) -> None:
        with self.assertRaisesRegex(TypeError, "Decimal"):
            replace(requirements()[0], minimum_coverage=0.98)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "threshold_source"):
            replace(requirements()[0], threshold_source="")


if __name__ == "__main__":
    unittest.main()
