import unittest
from dataclasses import replace

from a_share_platform.domain.factor_validation import (
    BHFamilySpec,
    HypothesisPValue,
    ValidationCalculationStatus,
    WalkForwardSample,
    WalkForwardSpec,
    benjamini_hochberg,
    purged_embargoed_walk_forward,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode


def hypothesis(
    hypothesis_id: str,
    p_value: float | None,
    *,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
    missing_reason: str | None = None,
) -> HypothesisPValue:
    return HypothesisPValue(
        hypothesis_id=hypothesis_id,
        p_value=p_value,
        p_value_version_id="pvalue:hac-t:v2",
        data_mode=data_mode,
        trust_state=trust_state,
        missing_reason=missing_reason,
    )


def family_spec(*, minimum_hypotheses: int = 4) -> BHFamilySpec:
    return BHFamilySpec(
        family_id="family:fundamental-v0:primary",
        family_version="family-membership:2024q4:v1",
        alpha=0.05,
        minimum_hypotheses=minimum_hypotheses,
        method_version="benjamini-hochberg-step-up:v1",
        tie_break_version="p-value-then-hypothesis-id:v1",
    )


def sample(
    session_index: int,
    *,
    horizon: int = 2,
    data_mode: DataMode = DataMode.STRICT_HISTORICAL,
    trust_state: DataTrustState = DataTrustState.PIT_VERIFIED,
    available: bool = True,
    missing_reason: str | None = None,
) -> WalkForwardSample:
    return WalkForwardSample(
        sample_id=f"sample:{session_index:02d}",
        session_index=session_index,
        label_end_session_index=session_index + horizon,
        feature_version_id="feature:quality:v3",
        label_version_id="label:forward-20d:v2",
        data_mode=data_mode,
        feature_trust_state=trust_state,
        label_trust_state=trust_state,
        available=available,
        missing_reason=missing_reason,
    )


class BenjaminiHochbergTest(unittest.TestCase):
    def test_hand_calculated_step_up_rejections_and_adjusted_p_values(self) -> None:
        result = benjamini_hochberg(
            (
                hypothesis("B", 0.04),
                hypothesis("D", 0.20),
                hypothesis("A", 0.01),
                hypothesis("C", 0.03),
            ),
            spec=family_spec(),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, ValidationCalculationStatus.QUANTIFIED)
        self.assertEqual(tuple(value.hypothesis_id for value in result.decisions), ("A", "C", "B", "D"))
        self.assertEqual(tuple(value.rank for value in result.decisions), (1, 2, 3, 4))
        self.assertEqual(result.rejected_hypothesis_ids, ("A",))
        expected_adjusted = (0.04, 0.05333333333333334, 0.05333333333333334, 0.20)
        for decision, expected in zip(result.decisions, expected_adjusted):
            self.assertAlmostEqual(decision.adjusted_p_value, expected, places=14)

    def test_ties_have_deterministic_id_order_and_equal_adjusted_p_values(self) -> None:
        values = (
            hypothesis("zeta", 0.02),
            hypothesis("alpha", 0.02),
            hypothesis("middle", 0.20),
        )
        result = benjamini_hochberg(
            tuple(reversed(values)),
            spec=family_spec(minimum_hypotheses=3),
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(
            tuple(value.hypothesis_id for value in result.decisions),
            ("alpha", "zeta", "middle"),
        )
        self.assertAlmostEqual(
            result.decisions[0].adjusted_p_value,
            result.decisions[1].adjusted_p_value,
        )
        self.assertEqual(result.rejected_hypothesis_ids, ("alpha", "zeta"))

    def test_missing_member_or_too_small_family_fails_closed(self) -> None:
        missing = benjamini_hochberg(
            (
                hypothesis("A", 0.01),
                hypothesis("B", None, missing_reason="HAC estimate unavailable"),
                hypothesis("C", 0.03),
                hypothesis("D", 0.04),
            ),
            spec=family_spec(),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        self.assertEqual(missing.status, ValidationCalculationStatus.UNAVAILABLE)
        self.assertEqual(missing.decisions, ())
        self.assertEqual(missing.missing_hypothesis_ids, ("B",))

        too_small = benjamini_hochberg(
            (hypothesis("A", 0.01), hypothesis("B", 0.02)),
            spec=family_spec(),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        self.assertEqual(too_small.status, ValidationCalculationStatus.UNAVAILABLE)
        self.assertIn("minimum_hypotheses=4", too_small.unavailable_reason or "")

    def test_current_p_values_cannot_be_relabelled_as_historical_family(self) -> None:
        current = tuple(
            hypothesis(
                value,
                0.01,
                data_mode=DataMode.CURRENT_RESEARCH,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )
            for value in ("A", "B", "C", "D")
        )
        result = benjamini_hochberg(
            current,
            spec=family_spec(),
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertFalse(result.historical_eligible)
        with self.assertRaisesRegex(PermissionError, "pit_verified|relabel"):
            benjamini_hochberg(
                current,
                spec=family_spec(),
                data_mode=DataMode.STRICT_HISTORICAL,
            )


class PurgedEmbargoedWalkForwardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.samples = tuple(sample(index) for index in range(12))
        self.spec = WalkForwardSpec(
            initial_training_sessions=6,
            test_sessions=2,
            step_sessions=3,
            horizon_sessions=2,
            purge_sessions=1,
            embargo_sessions=1,
            minimum_training_samples=3,
            split_version="expanding-purged-embargoed:v1",
        )

    def test_expanding_folds_have_explicit_train_test_purge_and_embargo_boundaries(self) -> None:
        result = purged_embargoed_walk_forward(
            tuple(reversed(self.samples)),
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )

        self.assertEqual(result.status, ValidationCalculationStatus.QUANTIFIED)
        self.assertEqual(len(result.folds), 2)
        first, second = result.folds
        self.assertEqual(first.test_start_session_index, 6)
        self.assertEqual(first.test_end_session_index, 7)
        self.assertEqual(first.training_sample_ids, ("sample:00", "sample:01", "sample:02"))
        self.assertEqual(first.purged_sample_ids, ("sample:03", "sample:04", "sample:05"))
        self.assertEqual(first.test_sample_ids, ("sample:06", "sample:07"))
        self.assertEqual(first.embargoed_sample_ids, ("sample:08",))
        self.assertEqual(second.training_sample_ids, tuple(f"sample:{index:02d}" for index in range(6)))
        self.assertEqual(second.purged_sample_ids, ("sample:06", "sample:07", "sample:08"))
        self.assertEqual(second.test_sample_ids, ("sample:09", "sample:10"))
        self.assertEqual(second.embargoed_sample_ids, ("sample:11",))
        for fold in result.folds:
            self.assertTrue(set(fold.training_sample_ids).isdisjoint(fold.test_sample_ids))

    def test_horizon_mismatch_missing_sample_and_small_post_purge_train_fail_closed(self) -> None:
        mismatch = replace(self.samples[0], label_end_session_index=1)
        with self.assertRaisesRegex(ValueError, "horizon"):
            purged_embargoed_walk_forward(
                (mismatch, *self.samples[1:]),
                spec=self.spec,
                data_mode=DataMode.STRICT_HISTORICAL,
            )

        unavailable = replace(
            self.samples[4],
            available=False,
            missing_reason="forward label unavailable",
        )
        missing = purged_embargoed_walk_forward(
            (*self.samples[:4], unavailable, *self.samples[5:]),
            spec=self.spec,
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        self.assertEqual(missing.status, ValidationCalculationStatus.UNAVAILABLE)
        self.assertEqual(missing.folds, ())
        self.assertEqual(missing.missing_sample_ids, ("sample:04",))

        too_small = purged_embargoed_walk_forward(
            self.samples,
            spec=replace(self.spec, minimum_training_samples=4),
            data_mode=DataMode.STRICT_HISTORICAL,
        )
        self.assertEqual(too_small.status, ValidationCalculationStatus.UNAVAILABLE)
        self.assertIn("post-purge training", too_small.unavailable_reason or "")

    def test_embargo_step_and_current_to_historical_relabel_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, r"test_sessions \+ embargo_sessions"):
            replace(self.spec, step_sessions=2)

        current_samples = tuple(
            replace(
                value,
                data_mode=DataMode.CURRENT_RESEARCH,
                feature_trust_state=DataTrustState.NORMALIZED_CURRENT,
                label_trust_state=DataTrustState.NORMALIZED_CURRENT,
            )
            for value in self.samples
        )
        current = purged_embargoed_walk_forward(
            current_samples,
            spec=self.spec,
            data_mode=DataMode.CURRENT_RESEARCH,
        )
        self.assertFalse(current.historical_eligible)
        with self.assertRaisesRegex(PermissionError, "pit_verified|relabel"):
            purged_embargoed_walk_forward(
                current_samples,
                spec=self.spec,
                data_mode=DataMode.STRICT_HISTORICAL,
            )


if __name__ == "__main__":
    unittest.main()
