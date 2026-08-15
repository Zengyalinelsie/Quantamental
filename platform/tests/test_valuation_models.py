import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from a_share_platform.domain.features import FeaturePeriod
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
    ValuationComponentResult,
    ValuationComponentStatus,
    ValuationExpectationMetric,
    ValuationInputProvenance,
    ValuationMetric,
)
from a_share_platform.domain.valuation_models import (
    AnalystRevisionInput,
    AnalystSourceAttestation,
    FundamentalAnchorInput,
    FundamentalAnchorMethod,
    RelativeReferenceKind,
    RelativeValuationReferenceInput,
    UnavailableAnalystRevisionInput,
    UnavailableFundamentalAnchorInput,
    ValuationModelStatus,
    analyst_revision_model_v0,
    fundamental_anchor_model_v0,
    implied_expectation_model_v0,
    industry_valuation_policy_v0,
    relative_valuation_model_v0,
)

DECISION_TIME = datetime(2025, 4, 30, 15, 0, tzinfo=UTC)
AVAILABLE_AT = DECISION_TIME - timedelta(minutes=1)
HASH_A = "sha256:" + "a" * 64


def provenance(name: str) -> ValuationInputProvenance:
    return ValuationInputProvenance(
        dataset_version_id=f"dataset:{name}:v1",
        method_id=f"method:{name}",
        method_version="v1",
        source_observation_ids=(f"observation:{name}:v1",),
        content_hashes=(HASH_A,),
    )


def subject(metric: ValuationMetric, value: str) -> ValuationComponentResult:
    return ValuationComponentResult(
        metric=metric,
        status=ValuationComponentStatus.QUANTIFIED,
        value=Decimal(value),
        unit=MetricUnit.RATIO,
        currency=None,
        numerator_period=FeaturePeriod.TTM,
        denominator_period=FeaturePeriod.INSTANT,
        provenance=provenance(f"subject:{metric.value}"),
        unavailable_reasons=(),
    )


def reference(
    metric: ValuationMetric,
    kind: RelativeReferenceKind,
    value: str | None,
) -> RelativeValuationReferenceInput:
    return RelativeValuationReferenceInput(
        metric=metric,
        reference_kind=kind,
        median_value=None if value is None else Decimal(value),
        observation_count=0 if value is None else 12,
        unit=MetricUnit.RATIO,
        comparable_set_version_id="comparable-set:C30:2025q1:v1",
        provenance=provenance(f"reference:{kind.value}:{metric.value}"),
        data_mode=DataMode.CURRENT_RESEARCH,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
        unavailable_reasons=() if value is not None else (f"{kind.value} unavailable",),
    )


def anchor(
    method: FundamentalAnchorMethod = FundamentalAnchorMethod.FCF_GROWING_PERPETUITY,
    *,
    template: IndustryTemplateId = IndustryTemplateId.NON_FINANCIAL_GENERAL,
) -> FundamentalAnchorInput:
    is_bank = method is FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK
    return FundamentalAnchorInput(
        method=method,
        industry_template_id=template,
        current_price=Decimal("12" if is_bank else "10"),
        base_value_per_share_lower=Decimal("10" if is_bank else "1"),
        base_value_per_share_upper=Decimal("10" if is_bank else "1.2"),
        profitability_lower=Decimal("0.12") if is_bank else None,
        profitability_upper=Decimal("0.15") if is_bank else None,
        discount_rate_lower=Decimal("0.10"),
        discount_rate_upper=Decimal("0.11" if is_bank else "0.12"),
        perpetual_growth_lower=Decimal("0.03" if is_bank else "0.02"),
        perpetual_growth_upper=Decimal("0.04" if is_bank else "0.03"),
        current_price_unit=MetricUnit.CURRENCY_PER_SHARE,
        base_value_per_share_unit=MetricUnit.CURRENCY_PER_SHARE,
        rate_unit=MetricUnit.RATIO,
        currency="CNY",
        assumptions=("Stable normalized fundamentals inside the declared interval.",),
        invalidation_conditions=("Capital structure or normalized base changes materially.",),
        price_provenance=provenance(f"anchor-price:{method.value}"),
        fundamental_provenance=provenance(f"anchor-fundamental:{method.value}"),
        assumption_provenance=provenance(f"anchor-assumptions:{method.value}"),
        data_mode=DataMode.CURRENT_RESEARCH,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
    )


def analyst(*, available: bool) -> AnalystRevisionInput:
    attestation = AnalystSourceAttestation(
        attestation_id="attestation:analyst:test:v1",
        provider_policy=ProviderFieldPolicy(
            provider_id="provider:analyst:test",
            field=DataField.ANALYST_CONSENSUS,
            tier=ProviderTier.PRIMARY,
            markets=frozenset({"CN"}),
            permitted_uses=frozenset({ProviderUse.PRIVATE_LOCAL_RESEARCH}),
            license_status=LicenseStatus.VERIFIED,
            trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
            coverage=CoverageStatus.AVAILABLE,
        ),
        market="CN",
        provider_use=ProviderUse.PRIVATE_LOCAL_RESEARCH,
        source_policy_version="analyst-consensus-policy:test:v1",
        license_evidence_id="license-evidence:analyst:test:v1",
        approval_id="approval:analyst:test:v1",
        qualified_at=DECISION_TIME - timedelta(days=90),
        valid_until=DECISION_TIME + timedelta(days=90),
    )
    return AnalystRevisionInput(
        expectation_metric=ValuationExpectationMetric.GROWTH,
        current_lower=Decimal("0.10") if available else None,
        current_upper=Decimal("0.14") if available else None,
        prior_lower=Decimal("0.08") if available else None,
        prior_upper=Decimal("0.10") if available else None,
        unit=MetricUnit.RATIO,
        consensus_definition_version="analyst-consensus-definition:test:v1",
        target_period_end=date(2025, 12, 31),
        forecast_horizon_days=365,
        current_snapshot_at=AVAILABLE_AT,
        prior_snapshot_at=AVAILABLE_AT - timedelta(days=30),
        source_attestation=attestation if available else None,
        current_provider_id="provider:analyst:test",
        prior_provider_id="provider:analyst:test",
        current_provenance=provenance("analyst-consensus:current"),
        prior_provenance=provenance("analyst-consensus:prior"),
        data_mode=DataMode.CURRENT_RESEARCH,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        decision_time=DECISION_TIME,
        latest_source_available_at=AVAILABLE_AT,
        unavailable_reasons=() if available else ("qualified analyst source unavailable",),
    )


class IndustryValuationPolicyV0Test(unittest.TestCase):
    def test_bank_and_non_financial_policies_use_distinct_methods_and_metrics(self) -> None:
        bank = industry_valuation_policy_v0(IndustryTemplateId.BANK)
        general = industry_valuation_policy_v0(IndustryTemplateId.NON_FINANCIAL_GENERAL)

        self.assertEqual(
            bank.anchor_method,
            FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK,
        )
        self.assertEqual(bank.expectation_metric, ValuationExpectationMetric.RETURN_ON_EQUITY)
        self.assertEqual(
            bank.relative_metrics,
            (ValuationMetric.EARNINGS_TO_PRICE, ValuationMetric.BOOK_TO_PRICE),
        )
        self.assertEqual(
            general.anchor_method,
            FundamentalAnchorMethod.FCF_GROWING_PERPETUITY,
        )
        self.assertEqual(general.expectation_metric, ValuationExpectationMetric.GROWTH)
        self.assertIn(ValuationMetric.ENTERPRISE_VALUE_TO_EBIT, general.relative_metrics)


class RelativeValuationModelV0Test(unittest.TestCase):
    def test_historical_industry_and_peer_yield_comparisons_match_hand_calculation(self) -> None:
        metric = ValuationMetric.EARNINGS_TO_PRICE
        result = relative_valuation_model_v0().calculate(
            subject(metric, "0.10"),
            tuple(
                reference(metric, kind, value)
                for kind, value in (
                    (RelativeReferenceKind.HISTORICAL, "0.08"),
                    (RelativeReferenceKind.INDUSTRY, "0.10"),
                    (RelativeReferenceKind.PEER, "0.125"),
                )
            ),
        )

        self.assertEqual(result.status, ValuationModelStatus.QUANTIFIED)
        self.assertEqual(
            result.comparison(RelativeReferenceKind.HISTORICAL).relative_gap, Decimal("0.25")
        )
        self.assertEqual(result.comparison(RelativeReferenceKind.INDUSTRY).relative_gap, Decimal(0))
        self.assertEqual(
            result.comparison(RelativeReferenceKind.PEER).relative_gap, Decimal("-0.2")
        )
        self.assertEqual(result.comparable_set_version_id, "comparable-set:C30:2025q1:v1")

    def test_ev_to_ebit_uses_lower_is_cheaper_direction(self) -> None:
        metric = ValuationMetric.ENTERPRISE_VALUE_TO_EBIT
        result = relative_valuation_model_v0().calculate(
            subject(metric, "6"),
            (
                reference(metric, RelativeReferenceKind.HISTORICAL, None),
                reference(metric, RelativeReferenceKind.INDUSTRY, None),
                reference(metric, RelativeReferenceKind.PEER, "8"),
            ),
        )

        self.assertEqual(result.status, ValuationModelStatus.PARTIAL)
        self.assertEqual(
            result.comparison(RelativeReferenceKind.PEER).relative_gap,
            Decimal(8) / Decimal(6) - Decimal(1),
        )

    def test_missing_reference_is_partial_and_never_becomes_numeric_zero(self) -> None:
        metric = ValuationMetric.BOOK_TO_PRICE
        result = relative_valuation_model_v0().calculate(
            subject(metric, "0.20"),
            (
                reference(metric, RelativeReferenceKind.HISTORICAL, "0.18"),
                reference(metric, RelativeReferenceKind.INDUSTRY, None),
                reference(metric, RelativeReferenceKind.PEER, None),
            ),
        )

        self.assertEqual(result.status, ValuationModelStatus.PARTIAL)
        self.assertIsNone(result.comparison(RelativeReferenceKind.INDUSTRY).relative_gap)
        self.assertIn(
            "industry unavailable",
            result.comparison(RelativeReferenceKind.INDUSTRY).unavailable_reasons,
        )

    def test_non_positive_non_finite_mismatch_and_duplicate_references_fail_closed(self) -> None:
        metric = ValuationMetric.EARNINGS_TO_PRICE
        with self.assertRaisesRegex(ValueError, "positive"):
            replace(
                reference(metric, RelativeReferenceKind.PEER, "0.10"),
                median_value=Decimal(0),
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            replace(
                reference(metric, RelativeReferenceKind.PEER, "0.10"),
                median_value=Decimal("NaN"),
            )
        peer = reference(metric, RelativeReferenceKind.PEER, "0.10")
        with self.assertRaisesRegex(ValueError, "metric"):
            relative_valuation_model_v0().calculate(
                subject(ValuationMetric.BOOK_TO_PRICE, "0.20"),
                (peer,),
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            relative_valuation_model_v0().calculate(
                subject(metric, "0.10"),
                (peer, peer),
            )

    def test_reference_set_requires_one_mode_trust_and_decision_time(self) -> None:
        metric = ValuationMetric.EARNINGS_TO_PRICE
        current = reference(metric, RelativeReferenceKind.INDUSTRY, "0.10")
        strict = replace(
            reference(metric, RelativeReferenceKind.PEER, "0.11"),
            data_mode=DataMode.STRICT_HISTORICAL,
            trust_state=DataTrustState.PIT_VERIFIED,
        )

        with self.assertRaisesRegex(PermissionError, "mode/trust"):
            relative_valuation_model_v0().calculate(
                subject(metric, "0.10"),
                (
                    reference(metric, RelativeReferenceKind.HISTORICAL, "0.09"),
                    current,
                    strict,
                ),
            )

    def test_omitted_reference_kind_is_rejected_instead_of_silently_partial(self) -> None:
        metric = ValuationMetric.EARNINGS_TO_PRICE
        with self.assertRaisesRegex(ValueError, "each require"):
            relative_valuation_model_v0().calculate(
                subject(metric, "0.10"),
                (reference(metric, RelativeReferenceKind.PEER, "0.11"),),
            )


class FundamentalAnchorAndImpliedExpectationV0Test(unittest.TestCase):
    def test_non_financial_fcf_anchor_returns_interval_not_target_price(self) -> None:
        result = fundamental_anchor_model_v0().calculate(anchor())

        self.assertEqual(result.status, ValuationModelStatus.QUANTIFIED)
        self.assertEqual(result.fair_value_lower, Decimal("10.2"))
        self.assertEqual(
            result.fair_value_upper,
            Decimal("1.2") * Decimal("1.03") / Decimal("0.07"),
        )
        self.assertEqual(result.expected_return_lower, Decimal("0.02"))
        self.assertIsNone(getattr(result, "target_price", None))
        self.assertEqual(result.expectation_metric, ValuationExpectationMetric.GROWTH)
        self.assertEqual(result.fundamental_expectation_lower, Decimal("0.02"))
        self.assertEqual(result.fundamental_expectation_upper, Decimal("0.03"))
        self.assertEqual(
            set(result.provenance.dataset_version_ids),
            {
                "dataset:anchor-price:fcf_growing_perpetuity:v1",
                "dataset:anchor-fundamental:fcf_growing_perpetuity:v1",
                "dataset:anchor-assumptions:fcf_growing_perpetuity:v1",
            },
        )
        self.assertEqual(
            set(result.input_method_versions),
            {
                "method:anchor-assumptions:fcf_growing_perpetuity@v1",
                "method:anchor-fundamental:fcf_growing_perpetuity@v1",
                "method:anchor-price:fcf_growing_perpetuity@v1",
            },
        )

    def test_bank_anchor_uses_justified_price_to_book(self) -> None:
        value = anchor(
            FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK,
            template=IndustryTemplateId.BANK,
        )
        result = fundamental_anchor_model_v0().calculate(value)

        self.assertEqual(
            result.fair_value_lower,
            Decimal(10) * (Decimal("0.12") - Decimal("0.03")) / Decimal("0.08"),
        )
        self.assertEqual(
            result.fair_value_upper,
            Decimal(10) * (Decimal("0.15") - Decimal("0.04")) / Decimal("0.06"),
        )
        self.assertEqual(
            result.expectation_metric,
            ValuationExpectationMetric.RETURN_ON_EQUITY,
        )

    def test_market_price_implies_growth_for_non_financial_and_roe_for_bank(self) -> None:
        general = implied_expectation_model_v0().calculate(anchor())
        bank = implied_expectation_model_v0().calculate(
            anchor(
                FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK,
                template=IndustryTemplateId.BANK,
            )
        )

        self.assertEqual(general.expectation_metric, ValuationExpectationMetric.GROWTH)
        self.assertEqual(
            general.lower,
            (Decimal(10) * Decimal("0.10") - Decimal("1.2")) / Decimal("11.2"),
        )
        self.assertEqual(
            general.upper,
            (Decimal(10) * Decimal("0.12") - Decimal(1)) / Decimal(11),
        )
        self.assertEqual(
            bank.expectation_metric,
            ValuationExpectationMetric.RETURN_ON_EQUITY,
        )
        self.assertEqual(bank.lower, Decimal("0.112"))
        self.assertEqual(bank.upper, Decimal("0.126"))

    def test_bank_implied_roe_uses_full_endpoint_envelope_below_price_to_book_one(self) -> None:
        value = replace(
            anchor(
                FundamentalAnchorMethod.BANK_JUSTIFIED_PRICE_TO_BOOK,
                template=IndustryTemplateId.BANK,
            ),
            current_price=Decimal(8),
            base_value_per_share_lower=Decimal(10),
            base_value_per_share_upper=Decimal(12),
            discount_rate_lower=Decimal("0.10"),
            discount_rate_upper=Decimal("0.12"),
            perpetual_growth_lower=Decimal("0.02"),
            perpetual_growth_upper=Decimal("0.04"),
        )
        result = implied_expectation_model_v0().calculate(value)
        candidates = tuple(
            (Decimal(8) / book) * (discount - growth) + growth
            for book in (Decimal(10), Decimal(12))
            for discount in (Decimal("0.10"), Decimal("0.12"))
            for growth in (Decimal("0.02"), Decimal("0.04"))
        )

        self.assertEqual(result.lower, min(candidates))
        self.assertEqual(result.upper, max(candidates))

    def test_missing_anchor_inputs_are_explicitly_unavailable(self) -> None:
        missing = UnavailableFundamentalAnchorInput(
            method=FundamentalAnchorMethod.FCF_GROWING_PERPETUITY,
            industry_template_id=IndustryTemplateId.NON_FINANCIAL_GENERAL,
            currency="CNY",
            current_price_unit=MetricUnit.CURRENCY_PER_SHARE,
            base_value_per_share_unit=MetricUnit.CURRENCY_PER_SHARE,
            rate_unit=MetricUnit.RATIO,
            assumptions=("No FCF value was inferred.",),
            invalidation_conditions=("Compile a new frozen input after FCF is available.",),
            provenances=(provenance("anchor-unavailable"),),
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            decision_time=DECISION_TIME,
            latest_source_available_at=AVAILABLE_AT,
            unavailable_reasons=("qualified FCF per share is unavailable",),
        )

        anchor_result = fundamental_anchor_model_v0().calculate(missing)
        implied_result = implied_expectation_model_v0().calculate(missing)
        self.assertEqual(anchor_result.status, ValuationModelStatus.UNAVAILABLE)
        self.assertIsNone(anchor_result.fair_value_lower)
        self.assertEqual(implied_result.status, ValuationModelStatus.UNAVAILABLE)
        self.assertIsNone(implied_result.lower)

    def test_invalid_method_template_or_discount_growth_pair_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "industry template"):
            fundamental_anchor_model_v0().calculate(anchor(template=IndustryTemplateId.BANK))
        with self.assertRaisesRegex(ValueError, "discount rate"):
            replace(anchor(), discount_rate_lower=Decimal("0.02"))
        with self.assertRaisesRegex(ValueError, "currency_per_share"):
            replace(anchor(), current_price_unit=MetricUnit.CURRENCY)


class AnalystRevisionModelV0Test(unittest.TestCase):
    def test_unavailable_analyst_input_does_not_invent_provider_or_snapshot_identity(self) -> None:
        value = UnavailableAnalystRevisionInput(
            expectation_metric=ValuationExpectationMetric.GROWTH,
            unit=MetricUnit.RATIO,
            provenances=(),
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            decision_time=DECISION_TIME,
            latest_source_available_at=None,
            unavailable_reasons=("qualified analyst source unavailable",),
        )

        result = analyst_revision_model_v0().calculate(value)

        self.assertIs(result.status, ValuationModelStatus.UNAVAILABLE)
        self.assertIsNone(result.current_provider_id)
        self.assertIsNone(result.prior_provider_id)
        self.assertIsNone(result.current_snapshot_at)
        self.assertIsNone(result.prior_snapshot_at)
        self.assertIsNone(result.consensus_definition_version)
        self.assertIsNone(result.target_period_end)
        self.assertIsNone(result.provenance)

    def test_revision_interval_and_midpoint_match_hand_calculation(self) -> None:
        result = analyst_revision_model_v0().calculate(analyst(available=True))

        self.assertEqual(result.status, ValuationModelStatus.QUANTIFIED)
        self.assertEqual(result.revision_lower, Decimal(0))
        self.assertEqual(result.revision_upper, Decimal("0.06"))
        self.assertEqual(result.midpoint_revision, Decimal("0.03"))
        self.assertEqual(result.current_provider_id, "provider:analyst:test")
        self.assertEqual(result.prior_provider_id, "provider:analyst:test")
        self.assertEqual(
            set(result.provenance.dataset_version_ids),
            {
                "dataset:analyst-consensus:current:v1",
                "dataset:analyst-consensus:prior:v1",
            },
        )

    def test_unqualified_source_is_explicitly_unavailable_without_zero(self) -> None:
        result = analyst_revision_model_v0().calculate(analyst(available=False))

        self.assertEqual(result.status, ValuationModelStatus.UNAVAILABLE)
        self.assertIsNone(result.revision_lower)
        self.assertIsNone(result.midpoint_revision)
        self.assertEqual(result.unavailable_reasons, ("qualified analyst source unavailable",))

    def test_numeric_revision_requires_a_valid_source_attestation(self) -> None:
        with self.assertRaisesRegex(PermissionError, "source attestation"):
            replace(
                analyst(available=True),
                source_attestation=None,
            )

    def test_attestation_provider_must_match_both_consensus_snapshots(self) -> None:
        valid = analyst(available=True)

        with self.assertRaisesRegex(PermissionError, "provider does not match"):
            replace(valid, current_provider_id="provider:other")
        with self.assertRaisesRegex(PermissionError, "provider does not match"):
            replace(valid, prior_provider_id="provider:other")

    def test_attestation_license_timing_and_comparability_fail_closed(self) -> None:
        valid = analyst(available=True)
        assert valid.source_attestation is not None
        unverified_policy = replace(
            valid.source_attestation.provider_policy,
            license_status=LicenseStatus.DATA_TERMS_REVIEW_REQUIRED,
        )
        with self.assertRaisesRegex(PermissionError, "license"):
            replace(
                valid.source_attestation,
                provider_policy=unverified_policy,
            )
        with self.assertRaisesRegex(ValueError, "prior_snapshot_at"):
            replace(valid, prior_snapshot_at=valid.current_snapshot_at)
        with self.assertRaisesRegex(PermissionError, "qualified after"):
            replace(
                valid,
                source_attestation=replace(
                    valid.source_attestation,
                    qualified_at=DECISION_TIME + timedelta(minutes=1),
                    valid_until=DECISION_TIME + timedelta(days=90),
                ),
            )
        with self.assertRaisesRegex(PermissionError, "expired"):
            replace(
                valid,
                source_attestation=replace(
                    valid.source_attestation,
                    valid_until=DECISION_TIME - timedelta(days=1),
                ),
            )
        with self.assertRaisesRegex(PermissionError, "trust ceiling"):
            replace(
                valid,
                source_attestation=replace(
                    valid.source_attestation,
                    provider_policy=replace(
                        valid.source_attestation.provider_policy,
                        trust_ceiling=DataTrustState.RAW,
                    ),
                ),
            )
        with self.assertRaisesRegex(PermissionError, "use does not match"):
            replace(
                valid,
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.PIT_VERIFIED,
            )


if __name__ == "__main__":
    unittest.main()
