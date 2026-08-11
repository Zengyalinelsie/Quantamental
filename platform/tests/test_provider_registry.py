import unittest

from a_share_platform.application.provider_registry import build_p2_provider_registry
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import (
    DataField,
    LicenseStatus,
    ProviderPermissionDenied,
    ProviderTier,
    ProviderUse,
)


class ProviderRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = build_p2_provider_registry()

    def test_primary_fallback_and_authority_are_explicit(self) -> None:
        policies = self.registry.policies_for(DataField.SECURITY_IDENTITY)
        self.assertEqual(
            [(policy.provider_id, policy.tier) for policy in policies],
            [
                ("a_share_mcp_baostock", ProviderTier.PRIMARY),
                ("a_share_identity_universe", ProviderTier.FALLBACK),
                ("akshare", ProviderTier.FALLBACK),
                ("official_exchanges", ProviderTier.AUTHORITY),
            ],
        )

    def test_composed_identity_source_is_private_local_only(self) -> None:
        for field in (
            DataField.SECURITY_IDENTITY,
            DataField.IDENTIFIER_HISTORY,
            DataField.LISTING_STATUS,
            DataField.INDUSTRY_MEMBERSHIP,
            DataField.BENCHMARK_MEMBERSHIP,
        ):
            policy = self.registry.policy("a_share_identity_universe", field)
            self.assertEqual(
                policy.permitted_uses,
                frozenset({ProviderUse.PRIVATE_LOCAL_RESEARCH}),
            )
            self.assertNotIn(ProviderUse.STRICT_HISTORICAL, policy.permitted_uses)
            self.assertIs(policy.trust_ceiling, DataTrustState.NORMALIZED_CURRENT)

    def test_prototype_primary_is_limited_to_shanghai_and_shenzhen(self) -> None:
        shanghai = self.registry.require(
            DataField.RAW_DAILY_BAR,
            ProviderUse.CURRENT_RESEARCH,
            market="XSHG",
        )
        self.assertEqual(shanghai.provider_id, "a_share_mcp_baostock")

        beijing = self.registry.require(
            DataField.RAW_DAILY_BAR,
            ProviderUse.CURRENT_RESEARCH,
            market="XBSE",
        )
        self.assertEqual(beijing.provider_id, "akshare")

    def test_free_sources_cannot_be_promoted_to_strict_or_production_use(self) -> None:
        for use in (ProviderUse.STRICT_HISTORICAL, ProviderUse.PRODUCTION_DECISION):
            with self.subTest(use=use), self.assertRaises(ProviderPermissionDenied):
                self.registry.require(DataField.RAW_DAILY_BAR, use, market="XSHG")

    def test_code_license_does_not_grant_data_redistribution(self) -> None:
        for provider_id in ("a_share_mcp_baostock", "akshare"):
            policy = self.registry.policy(provider_id, DataField.RAW_DAILY_BAR)
            self.assertEqual(policy.license_status, LicenseStatus.DATA_TERMS_REVIEW_REQUIRED)
            self.assertNotIn(ProviderUse.RAW_BULK_PERSISTENCE, policy.permitted_uses)
            self.assertNotIn(ProviderUse.EXTERNAL_REDISTRIBUTION, policy.permitted_uses)

    def test_provider_observations_cannot_self_promote_to_pit_verified(self) -> None:
        for policy in self.registry.policies_for(DataField.RAW_DAILY_BAR):
            self.assertIsNot(policy.trust_ceiling, DataTrustState.PIT_VERIFIED)

    def test_coverage_gaps_and_private_local_approval_remain_visible(self) -> None:
        adjustment = self.registry.policy(
            "a_share_mcp_baostock",
            DataField.ADJUSTMENT_FACTOR,
        )
        self.assertTrue(adjustment.is_partial)
        self.assertIn("empty result", adjustment.warning)

        share_capital = self.registry.require(
            DataField.SHARE_CAPITAL,
            ProviderUse.PRIVATE_LOCAL_RESEARCH,
            market="XSHG",
        )
        self.assertEqual(share_capital.provider_id, "akshare")
        self.assertIs(share_capital.trust_ceiling, DataTrustState.NORMALIZED_CURRENT)
        self.assertIn("private local", share_capital.warning)
        for use in (
            ProviderUse.STRICT_HISTORICAL,
            ProviderUse.EXTERNAL_REDISTRIBUTION,
            ProviderUse.PRODUCTION_DECISION,
        ):
            with self.subTest(use=use), self.assertRaises(ProviderPermissionDenied):
                self.registry.require(DataField.SHARE_CAPITAL, use, market="XSHG")


if __name__ == "__main__":
    unittest.main()
