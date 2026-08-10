"""Provider qualification and field-level data-use contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .pit import DataTrustState


class DataField(str, Enum):
    SECURITY_IDENTITY = "security_identity"
    IDENTIFIER_HISTORY = "identifier_history"
    LISTING_STATUS = "listing_status"
    TRADING_CALENDAR = "trading_calendar"
    RAW_DAILY_BAR = "raw_daily_bar"
    ADJUSTMENT_FACTOR = "adjustment_factor"
    TRADING_STATUS = "trading_status"
    PRICE_LIMIT = "price_limit"
    INDUSTRY_MEMBERSHIP = "industry_membership"
    BENCHMARK_MEMBERSHIP = "benchmark_membership"
    CORPORATE_ACTION = "corporate_action"
    SHARE_CAPITAL = "share_capital"
    ANNOUNCEMENT = "announcement"


class ProviderTier(str, Enum):
    PRIMARY = "primary"
    FALLBACK = "fallback"
    AUTHORITY = "authority"


class ProviderUse(str, Enum):
    LOCAL_FIXTURE = "local_fixture"
    CURRENT_RESEARCH = "current_research"
    INTERNAL_DISPLAY = "internal_display"
    STRICT_HISTORICAL = "strict_historical"
    RAW_BULK_PERSISTENCE = "raw_bulk_persistence"
    EXTERNAL_REDISTRIBUTION = "external_redistribution"
    PRODUCTION_DECISION = "production_decision"


class LicenseStatus(str, Enum):
    DATA_TERMS_REVIEW_REQUIRED = "data_terms_review_required"
    OFFICIAL_TERMS_REVIEW_REQUIRED = "official_terms_review_required"
    VERIFIED = "verified"


class CoverageStatus(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"


class ProviderPermissionDenied(RuntimeError):
    """Raised when no qualified provider may serve the requested use."""


@dataclass(frozen=True)
class ProviderFieldPolicy:
    provider_id: str
    field: DataField
    tier: ProviderTier
    markets: frozenset[str]
    permitted_uses: frozenset[ProviderUse]
    license_status: LicenseStatus
    trust_ceiling: DataTrustState
    coverage: CoverageStatus = CoverageStatus.AVAILABLE
    warning: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id.strip():
            raise ValueError("provider_id must not be empty")
        object.__setattr__(self, "field", DataField(self.field))
        object.__setattr__(self, "tier", ProviderTier(self.tier))
        object.__setattr__(self, "markets", frozenset(self.markets))
        object.__setattr__(
            self,
            "permitted_uses",
            frozenset(ProviderUse(item) for item in self.permitted_uses),
        )
        object.__setattr__(self, "license_status", LicenseStatus(self.license_status))
        object.__setattr__(self, "trust_ceiling", DataTrustState(self.trust_ceiling))
        object.__setattr__(self, "coverage", CoverageStatus(self.coverage))
        if not self.markets:
            raise ValueError("markets must not be empty")
        if self.coverage is CoverageStatus.PARTIAL and not self.warning.strip():
            raise ValueError("partial coverage requires a warning")
        restricted = {
            ProviderUse.RAW_BULK_PERSISTENCE,
            ProviderUse.EXTERNAL_REDISTRIBUTION,
            ProviderUse.PRODUCTION_DECISION,
        }
        if self.license_status is not LicenseStatus.VERIFIED and self.permitted_uses & restricted:
            raise ValueError("unverified data terms cannot grant persistence or production uses")

    @property
    def is_partial(self) -> bool:
        return self.coverage is CoverageStatus.PARTIAL

    def allows(self, use: ProviderUse, market: str) -> bool:
        return ProviderUse(use) in self.permitted_uses and market in self.markets


class ProviderRegistry:
    def __init__(self, policies: tuple[ProviderFieldPolicy, ...]) -> None:
        keyed: dict[tuple[str, DataField], ProviderFieldPolicy] = {}
        for policy in policies:
            key = (policy.provider_id, policy.field)
            if key in keyed:
                raise ValueError(f"duplicate provider field policy: {key}")
            keyed[key] = policy
        self._policies = keyed

    def policy(self, provider_id: str, field: DataField) -> ProviderFieldPolicy:
        try:
            return self._policies[(provider_id, DataField(field))]
        except KeyError as error:
            raise KeyError(f"provider {provider_id!r} has no policy for {DataField(field).value}") from error

    def policies_for(self, field: DataField) -> tuple[ProviderFieldPolicy, ...]:
        order = {
            ProviderTier.PRIMARY: 0,
            ProviderTier.FALLBACK: 1,
            ProviderTier.AUTHORITY: 2,
        }
        return tuple(
            sorted(
                (policy for policy in self._policies.values() if policy.field is DataField(field)),
                key=lambda policy: (order[policy.tier], policy.provider_id),
            )
        )

    def require(
        self,
        field: DataField,
        use: ProviderUse,
        *,
        market: str,
    ) -> ProviderFieldPolicy:
        for policy in self.policies_for(field):
            if policy.allows(use, market):
                return policy
        raise ProviderPermissionDenied(
            f"no provider is qualified for field={DataField(field).value}, "
            f"use={ProviderUse(use).value}, market={market}"
        )
