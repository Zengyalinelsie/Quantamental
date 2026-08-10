"""P2 provider decisions expressed as executable field policies."""

from __future__ import annotations

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.provider import (
    CoverageStatus,
    DataField,
    LicenseStatus,
    ProviderFieldPolicy,
    ProviderRegistry,
    ProviderTier,
    ProviderUse,
)

PROTOTYPE_USES = frozenset(
    {
        ProviderUse.LOCAL_FIXTURE,
        ProviderUse.CURRENT_RESEARCH,
        ProviderUse.INTERNAL_DISPLAY,
    }
)
PRIVATE_LOCAL_USES = PROTOTYPE_USES | frozenset({ProviderUse.PRIVATE_LOCAL_RESEARCH})
COMPOSED_IDENTITY_USES = frozenset({ProviderUse.PRIVATE_LOCAL_RESEARCH})
AUTHORITY_USES = frozenset(
    {
        ProviderUse.LOCAL_FIXTURE,
        ProviderUse.CURRENT_RESEARCH,
        ProviderUse.INTERNAL_DISPLAY,
    }
)


def _policy(
    provider_id: str,
    field: DataField,
    tier: ProviderTier,
    markets: frozenset[str],
    *,
    uses: frozenset[ProviderUse] = PROTOTYPE_USES,
    license_status: LicenseStatus = LicenseStatus.DATA_TERMS_REVIEW_REQUIRED,
    coverage: CoverageStatus = CoverageStatus.AVAILABLE,
    warning: str = "",
) -> ProviderFieldPolicy:
    return ProviderFieldPolicy(
        provider_id=provider_id,
        field=field,
        tier=tier,
        markets=markets,
        permitted_uses=uses,
        license_status=license_status,
        trust_ceiling=DataTrustState.NORMALIZED_CURRENT,
        coverage=coverage,
        warning=warning,
    )


def build_p2_provider_registry() -> ProviderRegistry:
    """Return the frozen P2 source decision without configuring provider SDKs."""

    sh_sz = frozenset({"XSHG", "XSHE"})
    all_a_share = frozenset({"XSHG", "XSHE", "XBSE"})
    baostock_fields = (
        DataField.SECURITY_IDENTITY,
        DataField.LISTING_STATUS,
        DataField.TRADING_CALENDAR,
        DataField.RAW_DAILY_BAR,
        DataField.TRADING_STATUS,
        DataField.INDUSTRY_MEMBERSHIP,
        DataField.BENCHMARK_MEMBERSHIP,
        DataField.CORPORATE_ACTION,
    )
    akshare_fields = (
        DataField.SECURITY_IDENTITY,
        DataField.IDENTIFIER_HISTORY,
        DataField.LISTING_STATUS,
        DataField.TRADING_CALENDAR,
        DataField.RAW_DAILY_BAR,
        DataField.ADJUSTMENT_FACTOR,
        DataField.TRADING_STATUS,
        DataField.PRICE_LIMIT,
        DataField.INDUSTRY_MEMBERSHIP,
        DataField.BENCHMARK_MEMBERSHIP,
        DataField.CORPORATE_ACTION,
    )
    policies = [
        *(
            _policy(
                "a_share_mcp_baostock",
                field,
                ProviderTier.PRIMARY,
                sh_sz,
            )
            for field in baostock_fields
        ),
        _policy(
            "a_share_mcp_baostock",
            DataField.ADJUSTMENT_FACTOR,
            ProviderTier.PRIMARY,
            sh_sz,
            coverage=CoverageStatus.PARTIAL,
            warning="2018 sample returned an empty result; fallback and reconciliation required",
        ),
        *(
            _policy(
                "baostock_sdk",
                field,
                ProviderTier.FALLBACK,
                sh_sz,
                uses=PRIVATE_LOCAL_USES,
                warning=(
                    "private local research persistence requires explicit user acknowledgement; "
                    "no external redistribution, strict historical, or production use"
                ),
            )
            for field in (
                DataField.TRADING_CALENDAR,
                DataField.RAW_DAILY_BAR,
            )
        ),
        *(
            _policy(
                "futu_quote",
                field,
                ProviderTier.FALLBACK,
                sh_sz,
                uses=(
                    PRIVATE_LOCAL_USES
                    if field is DataField.RAW_DAILY_BAR
                    else PROTOTYPE_USES
                ),
                coverage=CoverageStatus.PARTIAL,
                warning=(
                    "optional read-only OpenQuoteContext; OpenD entitlement, historical "
                    "coverage, provider retention restrictions, and PIT semantics remain visible"
                ),
            )
            for field in (
                DataField.TRADING_CALENDAR,
                DataField.RAW_DAILY_BAR,
                DataField.TRADING_STATUS,
            )
        ),
        *(
            _policy(
                "a_share_identity_universe",
                field,
                ProviderTier.FALLBACK,
                sh_sz,
                uses=COMPOSED_IDENTITY_USES,
                warning=(
                    "composed BaoStock/CNInfo observations are normalized_current only; "
                    "historical membership retrieval does not establish PIT availability"
                ),
            )
            for field in (
                DataField.SECURITY_IDENTITY,
                DataField.IDENTIFIER_HISTORY,
                DataField.LISTING_STATUS,
                DataField.INDUSTRY_MEMBERSHIP,
                DataField.BENCHMARK_MEMBERSHIP,
            )
        ),
        *(
            _policy("akshare", field, ProviderTier.FALLBACK, all_a_share)
            for field in akshare_fields
        ),
        *(
            _policy(
                "official_exchanges",
                field,
                ProviderTier.AUTHORITY,
                all_a_share,
                uses=AUTHORITY_USES,
                license_status=LicenseStatus.OFFICIAL_TERMS_REVIEW_REQUIRED,
            )
            for field in (
                DataField.SECURITY_IDENTITY,
                DataField.IDENTIFIER_HISTORY,
                DataField.LISTING_STATUS,
                DataField.TRADING_CALENDAR,
                DataField.TRADING_STATUS,
                DataField.PRICE_LIMIT,
                DataField.CORPORATE_ACTION,
                DataField.ANNOUNCEMENT,
            )
        ),
    ]
    return ProviderRegistry(tuple(policies))
