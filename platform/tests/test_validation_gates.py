import unittest

from a_share_platform.validation.gates import ResearchKind, policy_for


class ValidationPolicyTest(unittest.TestCase):
    def test_factor_policy_requires_inference_multiple_testing_and_oos(self) -> None:
        keys = {item.key for item in policy_for(ResearchKind.FACTOR).requirements}
        self.assertTrue(
            {"hac_or_block_bootstrap", "multiple_testing_fdr", "walk_forward_oos"}.issubset(keys)
        )

    def test_timing_policy_requires_calibration_and_shadow_forecasts(self) -> None:
        keys = {item.key for item in policy_for(ResearchKind.MARKET_TIMING).requirements}
        self.assertTrue({"probability_calibration", "shadow_forward_record"}.issubset(keys))

    def test_missing_reports_unfinished_requirements_in_policy_order(self) -> None:
        policy = policy_for(ResearchKind.EXECUTION)
        missing = policy.missing({"a_share_rule_replay", "fill_rate"})
        self.assertEqual(
            missing,
            ("implementation_shortfall", "slippage_model_error", "reconciliation"),
        )


if __name__ == "__main__":
    unittest.main()

