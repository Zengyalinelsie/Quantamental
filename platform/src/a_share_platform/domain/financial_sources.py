"""Provider-neutral financial-source qualification and staged-row contracts.

The domain core records what a source is allowed to supply without importing a
vendor SDK or HTTP client.  A source profile is deliberately fail-closed:
current data cannot become point-in-time data merely because a caller requests
``strict_historical`` and a read-through cache must be acknowledged explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .metrics import StatementType
from .pit import DataTrustState, FinancialPeriodType
from .run_context import DataMode

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_ISO_CURRENCY = re.compile(r"^[A-Z]{3}$")


class FinancialSourceRole(str, Enum):
    """The source's position in an explicit routing policy."""

    AUTHORITY = "authority"
    PRIMARY = "primary"
    FALLBACK = "fallback"
    SUPPLEMENT = "supplement"


class FinancialSourceAccessMode(str, Enum):
    """Observable side effect of querying a provider."""

    READ_ONLY = "read_only"
    READ_THROUGH_CACHE = "read_through_cache"


class FinancialSourceQualification(str, Enum):
    """Highest approved research use for a source profile version."""

    CANDIDATE = "candidate"
    NORMALIZED_CURRENT_APPROVED = "normalized_current_approved"
    PIT_APPROVED = "pit_approved"


class AvailabilityMethod(str, Enum):
    """How the market-availability timestamp was established."""

    PROVIDER_EXACT = "provider_exact"
    OFFICIAL_DISCLOSURE_EXACT = "official_disclosure_exact"
    CONSERVATIVE_RETRIEVAL_TIME = "conservative_retrieval_time"
    UNAVAILABLE = "unavailable"

    @property
    def is_exact(self) -> bool:
        return self in {
            self.PROVIDER_EXACT,
            self.OFFICIAL_DISCLOSURE_EXACT,
        }


class FinancialStatementScope(str, Enum):
    CONSOLIDATED = "consolidated"
    PARENT_COMPANY = "parent_company"


class FinancialValueBasis(str, Enum):
    POINT_IN_TIME = "point_in_time"
    CUMULATIVE_YTD = "cumulative_ytd"
    SINGLE_QUARTER = "single_quarter"
    TTM = "ttm"


class ReportVersionType(str, Enum):
    ORIGINAL = "original"
    CORRECTED = "corrected"
    RESTATED = "restated"


class FinancialSourcePermissionError(PermissionError):
    """A qualified source cannot be used under the requested access policy."""


class FinancialSourceUnavailable(LookupError):
    """No source profile can satisfy the requested route."""


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date")
    return value


@dataclass(frozen=True)
class FinancialSourceProfile:
    """Versioned qualification, permission, and capability record for a source."""

    profile_version: str
    provider_id: str
    role: FinancialSourceRole
    markets: frozenset[str]
    statements: frozenset[StatementType]
    access_mode: FinancialSourceAccessMode
    qualification: FinancialSourceQualification
    trust_ceiling: DataTrustState
    retention_allowed: bool
    bulk_persistence_allowed: bool
    supplies_revision_history: bool
    supplies_exact_available_at: bool
    max_rows_per_request: int
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.profile_version, "profile_version")
        _text(self.provider_id, "provider_id")
        object.__setattr__(self, "role", FinancialSourceRole(self.role))
        object.__setattr__(self, "access_mode", FinancialSourceAccessMode(self.access_mode))
        qualification = FinancialSourceQualification(self.qualification)
        trust_ceiling = DataTrustState(self.trust_ceiling)
        object.__setattr__(self, "qualification", qualification)
        object.__setattr__(self, "trust_ceiling", trust_ceiling)

        markets = frozenset(self.markets)
        if not markets:
            raise ValueError("markets must not be empty")
        for market in markets:
            _text(market, "market")
        object.__setattr__(self, "markets", markets)

        statements = frozenset(StatementType(item) for item in self.statements)
        if not statements:
            raise ValueError("statements must not be empty")
        object.__setattr__(self, "statements", statements)

        for name in (
            "retention_allowed",
            "bulk_persistence_allowed",
            "supplies_revision_history",
            "supplies_exact_available_at",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name} must be a boolean")
        if self.bulk_persistence_allowed and not self.retention_allowed:
            raise ValueError("bulk persistence requires retention permission")
        if type(self.max_rows_per_request) is not int or self.max_rows_per_request <= 0:
            raise ValueError("max_rows_per_request must be a positive integer")

        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)

        if qualification is FinancialSourceQualification.PIT_APPROVED and (
            trust_ceiling is not DataTrustState.PIT_VERIFIED
            or not self.supplies_revision_history
            or not self.supplies_exact_available_at
        ):
            raise ValueError(
                "PIT approval requires pit_verified trust, exact availability, "
                "and revision history"
            )
        if (
            qualification is FinancialSourceQualification.NORMALIZED_CURRENT_APPROVED
            and trust_ceiling is DataTrustState.RAW
        ):
            raise ValueError("current approval requires normalized_current trust or higher")

    def require_access(
        self,
        *,
        data_mode: DataMode,
        bulk_persistence: bool,
        allow_read_through_cache: bool,
    ) -> None:
        """Fail unless this exact profile is approved for the requested operation."""

        data_mode = DataMode(data_mode)
        if type(bulk_persistence) is not bool:
            raise TypeError("bulk_persistence must be a boolean")
        if type(allow_read_through_cache) is not bool:
            raise TypeError("allow_read_through_cache must be a boolean")
        if self.qualification is FinancialSourceQualification.CANDIDATE:
            raise FinancialSourcePermissionError(
                f"provider {self.provider_id} is only a candidate"
            )
        if data_mode is DataMode.STRICT_HISTORICAL and (
            self.qualification is not FinancialSourceQualification.PIT_APPROVED
            or self.trust_ceiling is not DataTrustState.PIT_VERIFIED
        ):
            raise FinancialSourcePermissionError(
                f"provider {self.provider_id} is not approved for strict_historical"
            )
        if bulk_persistence and (
            not self.retention_allowed or not self.bulk_persistence_allowed
        ):
            raise FinancialSourcePermissionError(
                f"provider {self.provider_id} does not permit bulk persistence/retention"
            )
        if (
            self.access_mode is FinancialSourceAccessMode.READ_THROUGH_CACHE
            and not allow_read_through_cache
        ):
            raise FinancialSourcePermissionError(
                f"provider {self.provider_id} has a read-through cache side effect"
            )

    def supports(self, *, market: str, statement_type: StatementType) -> bool:
        return market in self.markets and StatementType(statement_type) in self.statements


@dataclass(frozen=True)
class ProviderFinancialRow:
    """One lossless, provider-neutral staged financial value before metric mapping."""

    row_id: str
    provider_id: str
    provider_table: str
    provider_record_id: str
    provider_field: str
    market: str
    source_symbol: str
    statement_type: StatementType
    statement_scope: FinancialStatementScope
    report_period_start: date
    report_period_end: date
    period_type: FinancialPeriodType
    value_basis: FinancialValueBasis
    raw_value: Decimal
    provider_unit: str
    scale_to_canonical: Decimal
    currency: str | None
    report_version_type: ReportVersionType
    revision_sequence: int
    announced_at: datetime | None
    available_at: datetime | None
    availability_method: AvailabilityMethod
    provider_updated_at: datetime | None
    retrieved_at: datetime
    raw_object_id: str
    raw_object_hash: str
    source_url: str
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "row_id",
            "provider_id",
            "provider_table",
            "provider_record_id",
            "provider_field",
            "market",
            "source_symbol",
            "provider_unit",
            "raw_object_id",
            "source_url",
        ):
            _text(getattr(self, name), name)
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        object.__setattr__(
            self, "statement_scope", FinancialStatementScope(self.statement_scope)
        )
        object.__setattr__(self, "period_type", FinancialPeriodType(self.period_type))
        object.__setattr__(self, "value_basis", FinancialValueBasis(self.value_basis))
        object.__setattr__(
            self, "report_version_type", ReportVersionType(self.report_version_type)
        )
        availability_method = AvailabilityMethod(self.availability_method)
        object.__setattr__(self, "availability_method", availability_method)

        start = _date(self.report_period_start, "report_period_start")
        end = _date(self.report_period_end, "report_period_end")
        if end < start:
            raise ValueError("report_period_end cannot precede report_period_start")

        if isinstance(self.raw_value, float):
            raise TypeError("raw_value must use Decimal; float is not allowed")
        if not isinstance(self.raw_value, Decimal):
            raise TypeError("raw_value must use Decimal")
        if not self.raw_value.is_finite():
            raise ValueError("raw_value must be finite")
        if isinstance(self.scale_to_canonical, float):
            raise TypeError("scale_to_canonical must use Decimal; float is not allowed")
        if not isinstance(self.scale_to_canonical, Decimal):
            raise TypeError("scale_to_canonical must use Decimal")
        if not self.scale_to_canonical.is_finite() or self.scale_to_canonical == 0:
            raise ValueError("scale_to_canonical must be finite and non-zero")
        if self.currency is not None and _ISO_CURRENCY.fullmatch(self.currency) is None:
            raise ValueError("currency must be a three-letter uppercase ISO code")

        if type(self.revision_sequence) is not int or self.revision_sequence < 0:
            raise ValueError("revision_sequence must be a non-negative integer")
        if (
            self.report_version_type in {ReportVersionType.CORRECTED, ReportVersionType.RESTATED}
            and self.revision_sequence <= 0
        ):
            raise ValueError("corrected/restated report requires positive revision_sequence")

        retrieved_at = _aware(self.retrieved_at, "retrieved_at")
        announced_at = (
            None if self.announced_at is None else _aware(self.announced_at, "announced_at")
        )
        available_at = (
            None if self.available_at is None else _aware(self.available_at, "available_at")
        )
        if self.provider_updated_at is not None:
            _aware(self.provider_updated_at, "provider_updated_at")
        if announced_at is not None and available_at is not None and available_at < announced_at:
            raise ValueError("available_at cannot precede announced_at")
        if available_at is not None and available_at > retrieved_at:
            raise ValueError("available_at cannot be later than retrieved_at")

        if availability_method.is_exact and available_at is None:
            raise ValueError("exact availability method requires available_at")
        if availability_method is AvailabilityMethod.CONSERVATIVE_RETRIEVAL_TIME and (
            available_at != retrieved_at
        ):
            raise ValueError("conservative availability must equal retrieved_at")
        if availability_method is AvailabilityMethod.UNAVAILABLE and available_at is not None:
            raise ValueError("available_at must be absent when availability is unavailable")

        if not isinstance(self.raw_object_hash, str) or _SHA256.fullmatch(
            self.raw_object_hash
        ) is None:
            raise ValueError("raw_object_hash must use sha256:<64 lowercase hex chars>")
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)

    @property
    def scaled_numeric_value(self) -> Decimal:
        return self.raw_value * self.scale_to_canonical

    @property
    def is_strict_time_eligible(self) -> bool:
        return self.availability_method.is_exact and self.available_at is not None


_CURRENT_ROLE_ORDER = {
    FinancialSourceRole.PRIMARY: 0,
    FinancialSourceRole.FALLBACK: 1,
    FinancialSourceRole.AUTHORITY: 2,
    FinancialSourceRole.SUPPLEMENT: 3,
}
_STRICT_ROLE_ORDER = {
    FinancialSourceRole.AUTHORITY: 0,
    FinancialSourceRole.PRIMARY: 1,
    FinancialSourceRole.FALLBACK: 2,
    FinancialSourceRole.SUPPLEMENT: 3,
}


@dataclass(frozen=True)
class FinancialSourceRouter:
    """Deterministic source selection with an explicit, reasoned fallback path."""

    profiles: tuple[FinancialSourceProfile, ...]

    def __post_init__(self) -> None:
        profiles = tuple(self.profiles)
        if not profiles:
            raise ValueError("profiles must not be empty")
        provider_ids = tuple(profile.provider_id for profile in profiles)
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("provider profiles must have unique provider_id values")
        object.__setattr__(self, "profiles", profiles)

    def primary(
        self,
        *,
        market: str,
        statement_type: StatementType,
        data_mode: DataMode,
        bulk_persistence: bool,
        allow_read_through_cache: bool,
    ) -> FinancialSourceProfile:
        return self._select(
            excluded_provider_ids=frozenset(),
            market=market,
            statement_type=statement_type,
            data_mode=data_mode,
            bulk_persistence=bulk_persistence,
            allow_read_through_cache=allow_read_through_cache,
        )

    def fallback_after(
        self,
        *,
        failed_provider_id: str,
        reason: str,
        market: str,
        statement_type: StatementType,
        data_mode: DataMode,
        bulk_persistence: bool,
        allow_read_through_cache: bool,
    ) -> FinancialSourceProfile:
        _text(failed_provider_id, "failed_provider_id")
        _text(reason, "fallback reason")
        known_ids = {profile.provider_id for profile in self.profiles}
        if failed_provider_id not in known_ids:
            raise ValueError("failed_provider_id is not present in this router")
        return self._select(
            excluded_provider_ids=frozenset({failed_provider_id}),
            market=market,
            statement_type=statement_type,
            data_mode=data_mode,
            bulk_persistence=bulk_persistence,
            allow_read_through_cache=allow_read_through_cache,
        )

    def _select(
        self,
        *,
        excluded_provider_ids: frozenset[str],
        market: str,
        statement_type: StatementType,
        data_mode: DataMode,
        bulk_persistence: bool,
        allow_read_through_cache: bool,
    ) -> FinancialSourceProfile:
        _text(market, "market")
        data_mode = DataMode(data_mode)
        statement_type = StatementType(statement_type)
        order = (
            _STRICT_ROLE_ORDER
            if data_mode is DataMode.STRICT_HISTORICAL
            else _CURRENT_ROLE_ORDER
        )
        candidates = sorted(
            (
                profile
                for profile in self.profiles
                if profile.provider_id not in excluded_provider_ids
                and profile.supports(market=market, statement_type=statement_type)
            ),
            key=lambda profile: (order[profile.role], profile.provider_id),
        )
        denials: list[str] = []
        for candidate in candidates:
            try:
                candidate.require_access(
                    data_mode=data_mode,
                    bulk_persistence=bulk_persistence,
                    allow_read_through_cache=allow_read_through_cache,
                )
            except FinancialSourcePermissionError as error:
                denials.append(str(error))
                continue
            return candidate
        detail = "; ".join(denials) if denials else "no profile covers the request"
        raise FinancialSourceUnavailable(
            f"no financial source available for data_mode={data_mode.value}, "
            f"market={market}, statement={statement_type.value}: {detail}"
        )
