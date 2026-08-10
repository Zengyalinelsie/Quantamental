import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

from a_share_platform.domain.features import (
    FeatureCalculationStatus,
    FeatureDefinition,
    FeatureFormula,
    FeatureInput,
    FeatureInputSpec,
    FeaturePeriod,
    FeatureSnapshot,
    FeatureValueStage,
    LabelSchema,
    LabelValue,
    MissingFeatureInputError,
    MissingPolicy,
    MissingPolicySpec,
    NeutralizationExposure,
    NeutralizationSpec,
    StandardizationSpec,
    WinsorizationSpec,
)
from a_share_platform.domain.metrics import MetricUnit

NOW = datetime(2026, 8, 10, 8, tzinfo=UTC)
FORMULA_HASH = "sha256:" + "a" * 64
INPUT_HASH_A = "sha256:" + "b" * 64
INPUT_HASH_B = "sha256:" + "c" * 64


def ratio_formula() -> FeatureFormula:
    return FeatureFormula(
        formula_id="formula:cash-conversion",
        version="v1",
        content_hash=FORMULA_HASH,
        evaluator=lambda values: values[0] / values[1],
    )


def definition(
    *,
    missing_policy: MissingPolicy = MissingPolicy.UNAVAILABLE,
    winsorization_version: str = "winsor:v1",
) -> FeatureDefinition:
    return FeatureDefinition(
        feature_id="feature:cash-conversion",
        version="v1",
        name="Operating cash flow to net profit",
        inputs=(
            FeatureInputSpec(
                name="operating_cash_flow",
                unit=MetricUnit.CURRENCY,
                currency="CNY",
                period=FeaturePeriod.TTM,
            ),
            FeatureInputSpec(
                name="net_profit",
                unit=MetricUnit.CURRENCY,
                currency="CNY",
                period=FeaturePeriod.TTM,
            ),
        ),
        output_unit=MetricUnit.RATIO,
        output_currency=None,
        output_period=FeaturePeriod.TTM,
        formula=ratio_formula(),
        missing_policy=MissingPolicySpec(policy=missing_policy, version="missing:v1"),
        winsorization=WinsorizationSpec(
            method="cross-sectional-quantile",
            version=winsorization_version,
            parameters=(("lower", "0.01"), ("upper", "0.99")),
        ),
        standardization=StandardizationSpec(
            method="cross-sectional-zscore",
            version="standardize:v1",
            parameters=(("ddof", "0"),),
        ),
        neutralization=NeutralizationSpec(
            method="cross-sectional-linear-residual",
            version="neutralize:v1",
            exposures=(NeutralizationExposure.INDUSTRY, NeutralizationExposure.SIZE),
            parameters=(),
        ),
    )


def input_value(
    name: str,
    value: Decimal | None,
    *,
    unit: MetricUnit = MetricUnit.CURRENCY,
    currency: str | None = "CNY",
    period: FeaturePeriod = FeaturePeriod.TTM,
    content_hash: str = INPUT_HASH_A,
) -> FeatureInput:
    return FeatureInput(
        name=name,
        value=value,
        unit=unit,
        currency=currency,
        period=period,
        source_id=f"fact:{name}:2026q2",
        source_version_id=f"dataset:{name}:v1",
        content_hash=content_hash,
    )


def complete_inputs() -> dict[str, FeatureInput]:
    return {
        "operating_cash_flow": input_value(
            "operating_cash_flow", Decimal(120), content_hash=INPUT_HASH_A
        ),
        "net_profit": input_value("net_profit", Decimal(100), content_hash=INPUT_HASH_B),
    }


class FeatureDefinitionContractTest(unittest.TestCase):
    def test_formula_is_purely_driven_by_typed_ordered_inputs(self) -> None:
        result = definition().calculate(complete_inputs())

        self.assertEqual(result.status, FeatureCalculationStatus.QUANTIFIED)
        self.assertEqual(result.value, Decimal("1.2"))
        self.assertEqual(result.missing_input_names, ())

    def test_unit_currency_and_period_mismatches_fail_closed(self) -> None:
        mismatches = (
            (
                "unit",
                input_value(
                    "net_profit",
                    Decimal(100),
                    unit=MetricUnit.RATIO,
                    currency=None,
                    content_hash=INPUT_HASH_B,
                ),
            ),
            (
                "currency",
                input_value(
                    "net_profit",
                    Decimal(100),
                    currency="USD",
                    content_hash=INPUT_HASH_B,
                ),
            ),
            (
                "period",
                input_value(
                    "net_profit",
                    Decimal(100),
                    period=FeaturePeriod.ANNUAL,
                    content_hash=INPUT_HASH_B,
                ),
            ),
        )
        for expected, incompatible in mismatches:
            with self.subTest(expected=expected):
                values = complete_inputs()
                values["net_profit"] = incompatible
                with self.assertRaisesRegex(ValueError, expected):
                    definition().calculate(values)

    def test_missing_is_unavailable_and_never_passed_to_formula_as_zero(self) -> None:
        formula_called = False

        def should_not_run(values: tuple[Decimal, ...]) -> Decimal:
            nonlocal formula_called
            formula_called = True
            return Decimal(0)

        value = replace(
            definition(),
            formula=replace(ratio_formula(), evaluator=should_not_run),
        )
        inputs = complete_inputs()
        inputs["net_profit"] = input_value(
            "net_profit", None, content_hash=INPUT_HASH_B
        )

        result = value.calculate(inputs)

        self.assertEqual(result.status, FeatureCalculationStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertEqual(result.missing_input_names, ("net_profit",))
        self.assertFalse(formula_called)

    def test_reject_missing_policy_raises_instead_of_imputing(self) -> None:
        inputs = complete_inputs()
        inputs.pop("net_profit")

        with self.assertRaisesRegex(MissingFeatureInputError, "net_profit"):
            definition(missing_policy=MissingPolicy.REJECT).calculate(inputs)

    def test_unknown_input_and_non_decimal_output_are_rejected(self) -> None:
        inputs = complete_inputs()
        inputs["future_return_label"] = input_value(
            "future_return_label", Decimal("0.5"), content_hash=FORMULA_HASH
        )
        with self.assertRaisesRegex(ValueError, "unknown feature inputs"):
            definition().calculate(inputs)

        invalid_formula = replace(
            definition(),
            formula=replace(
                ratio_formula(),
                evaluator=lambda values: cast(Decimal, 1.2),
            ),
        )
        with self.assertRaisesRegex(TypeError, "Decimal"):
            invalid_formula.calculate(complete_inputs())

    def test_every_cross_sectional_transform_has_an_explicit_version(self) -> None:
        value = definition()
        self.assertEqual(value.winsorization.version, "winsor:v1")
        self.assertEqual(value.standardization.version, "standardize:v1")
        self.assertEqual(value.neutralization.version, "neutralize:v1")
        self.assertEqual(
            value.neutralization.exposures,
            (NeutralizationExposure.INDUSTRY, NeutralizationExposure.SIZE),
        )

        with self.assertRaisesRegex(ValueError, "parameters must be sorted"):
            replace(
                value.winsorization,
                parameters=(("upper", "0.99"), ("lower", "0.01")),
            )

    def test_definition_hash_is_deterministic_and_transform_versions_are_material(self) -> None:
        first = definition()
        same = definition()
        changed = definition(winsorization_version="winsor:v2")

        self.assertEqual(first.definition_hash, same.definition_hash)
        self.assertRegex(first.definition_hash, r"^sha256:[0-9a-f]{64}$")
        self.assertNotEqual(first.definition_hash, changed.definition_hash)


class FeatureSnapshotContractTest(unittest.TestCase):
    def test_snapshot_is_immutable_and_hashes_all_governed_inputs_deterministically(self) -> None:
        calculated = definition().calculate(complete_inputs())
        first = FeatureSnapshot.from_calculation(
            snapshot_id="feature-snapshot:600519:2026-08-10:cash-conversion:v1",
            definition=definition(),
            entity_id="security:CN:600519:XSHG",
            as_of=NOW,
            system_as_of=NOW,
            calculation=calculated,
            value_stage=FeatureValueStage.RAW,
            dataset_version_ids=("dataset:financials:v2", "dataset:financials:v1"),
            input_content_hashes=(INPUT_HASH_B, INPUT_HASH_A),
        )
        same = FeatureSnapshot.from_calculation(
            snapshot_id=first.snapshot_id,
            definition=definition(),
            entity_id=first.entity_id,
            as_of=first.as_of,
            system_as_of=first.system_as_of,
            calculation=calculated,
            value_stage=FeatureValueStage.RAW,
            dataset_version_ids=tuple(reversed(first.dataset_version_ids)),
            input_content_hashes=tuple(reversed(first.input_content_hashes)),
        )

        self.assertEqual(first.content_hash, same.content_hash)
        self.assertEqual(first.dataset_version_ids, tuple(sorted(first.dataset_version_ids)))
        self.assertEqual(first.storage_namespace, "feature_snapshots")
        with self.assertRaises(FrozenInstanceError):
            first.value = Decimal(2)  # type: ignore[misc]

    def test_unavailable_snapshot_retains_missing_reason_without_numeric_value(self) -> None:
        inputs = complete_inputs()
        inputs.pop("net_profit")
        calculated = definition().calculate(inputs)

        snapshot = FeatureSnapshot.from_calculation(
            snapshot_id="feature-snapshot:missing:v1",
            definition=definition(),
            entity_id="security:CN:600519:XSHG",
            as_of=NOW,
            system_as_of=NOW,
            calculation=calculated,
            value_stage=FeatureValueStage.RAW,
            dataset_version_ids=("dataset:financials:v1",),
            input_content_hashes=(INPUT_HASH_A,),
        )

        self.assertEqual(snapshot.status, FeatureCalculationStatus.UNAVAILABLE)
        self.assertIsNone(snapshot.value)
        self.assertEqual(snapshot.missing_input_names, ("net_profit",))


class LabelSeparationContractTest(unittest.TestCase):
    def test_labels_have_a_distinct_type_and_physical_namespace(self) -> None:
        label_schema = LabelSchema(
            label_id="label:forward-return-20d",
            version="v1",
            horizon_sessions=20,
            unit=MetricUnit.RATIO,
            currency=None,
        )
        label = LabelValue(
            schema=label_schema,
            entity_id="security:CN:600519:XSHG",
            as_of=NOW,
            value=Decimal("0.05"),
            dataset_version_id="dataset:forward-returns:v1",
        )

        self.assertEqual(label.storage_namespace, "research_labels")
        self.assertNotEqual(label.storage_namespace, FeatureSnapshot.storage_namespace)
        inputs: dict[str, object] = dict(complete_inputs())
        inputs["net_profit"] = label
        with self.assertRaisesRegex(TypeError, "FeatureInput"):
            definition().calculate(inputs)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
