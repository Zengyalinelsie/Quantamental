import unittest

from a_share_platform.domain.run_context import (
    DataMode,
    DeploymentStage,
    InvalidRunContextError,
    RunContext,
)


class RunContextTest(unittest.TestCase):
    def test_axis_values_match_spec_005(self) -> None:
        self.assertEqual(
            {item.value for item in DataMode},
            {"current_research", "strict_historical"},
        )
        self.assertEqual(
            {item.value for item in DeploymentStage},
            {"research", "shadow", "paper", "limited_live"},
        )

    def test_current_research_supports_each_deployment_stage(self) -> None:
        for stage in DeploymentStage:
            with self.subTest(stage=stage):
                context = RunContext(DataMode.CURRENT_RESEARCH, stage)
                self.assertIs(context.data_mode, DataMode.CURRENT_RESEARCH)
                self.assertIs(context.deployment_stage, stage)

    def test_strict_historical_is_valid_for_research(self) -> None:
        context = RunContext(DataMode.STRICT_HISTORICAL, DeploymentStage.RESEARCH)
        self.assertIs(context.data_mode, DataMode.STRICT_HISTORICAL)
        self.assertIs(context.deployment_stage, DeploymentStage.RESEARCH)

    def test_strict_historical_cannot_be_relabelled_as_forward_deployment(self) -> None:
        for stage in (
            DeploymentStage.SHADOW,
            DeploymentStage.PAPER,
            DeploymentStage.LIMITED_LIVE,
        ):
            with self.subTest(stage=stage), self.assertRaisesRegex(
                InvalidRunContextError, "cannot be combined"
            ):
                RunContext(DataMode.STRICT_HISTORICAL, stage)

    def test_string_values_are_normalized_to_enum_members(self) -> None:
        context = RunContext("current_research", "shadow")
        self.assertIs(context.data_mode, DataMode.CURRENT_RESEARCH)
        self.assertIs(context.deployment_stage, DeploymentStage.SHADOW)

    def test_unknown_axis_value_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            RunContext("current", DeploymentStage.RESEARCH)
        with self.assertRaises(ValueError):
            RunContext(DataMode.CURRENT_RESEARCH, "live")


if __name__ == "__main__":
    unittest.main()
