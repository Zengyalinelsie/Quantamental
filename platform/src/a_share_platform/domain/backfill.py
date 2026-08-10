"""Provider-neutral, fail-closed contracts for auditable A-share backfills."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import Enum

from .market_data import PriceAdjustment
from .pit import DataTrustState
from .provider import ProviderUse

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_A_SHARE_SYMBOL = re.compile(r"^(SH|SZ|BJ)\.\d{6}$")
_MARKETS = frozenset({"XSHG", "XSHE", "XBSE"})


def _required(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _date_interval(start_date: date, end_date: date) -> None:
    if not isinstance(start_date, date) or not isinstance(end_date, date):
        raise TypeError("backfill boundaries must be dates")
    if end_date < start_date:
        raise ValueError("end_date cannot precede start_date")


class BackfillScopeKind(str, Enum):
    SECURITY_MASTER = "security_master"
    INDEX_UNIVERSE = "index_universe"
    EXPLICIT_SYMBOLS = "explicit_symbols"


class BackfillDataDomain(str, Enum):
    SECURITY_MASTER = "security_master"
    UNIVERSE = "universe"
    RAW_DAILY_BAR = "raw_daily_bar"
    SHARE_CAPITAL = "share_capital"
    CORPORATE_ACTION = "corporate_action"
    TRADING_CALENDAR = "trading_calendar"


class BackfillJobStatus(str, Enum):
    PLANNED = "planned"
    BLOCKED = "blocked"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in {self.BLOCKED, self.SUCCEEDED}


class BackfillCheckpointStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self is self.SUCCEEDED


class DatasetQualityStatus(str, Enum):
    PASSED = "passed"
    WARNED = "warned"
    FAILED = "failed"


@dataclass(frozen=True)
class BackfillScope:
    scope_id: str
    name: str
    kind: BackfillScopeKind
    benchmark_code: str | None = None
    symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.scope_id, "scope_id")
        _required(self.name, "name")
        object.__setattr__(self, "kind", BackfillScopeKind(self.kind))
        object.__setattr__(self, "symbols", tuple(self.symbols))
        if len(self.symbols) != len(set(self.symbols)):
            raise ValueError("scope symbols must be unique")
        for symbol in self.symbols:
            if _A_SHARE_SYMBOL.fullmatch(symbol) is None:
                raise ValueError("scope symbols must use SH.000000, SZ.000000, or BJ.000000")
        if self.kind is BackfillScopeKind.INDEX_UNIVERSE:
            _required(self.benchmark_code or "", "benchmark_code")
            if self.symbols:
                raise ValueError("index-universe scope cannot embed explicit symbols")
        elif self.kind is BackfillScopeKind.EXPLICIT_SYMBOLS:
            if self.benchmark_code is not None:
                raise ValueError("explicit-symbol scope cannot have a benchmark_code")
            if not self.symbols:
                raise ValueError("explicit-symbol scope requires symbols")
        elif self.benchmark_code is not None or self.symbols:
            raise ValueError("security-master scope cannot have benchmark or symbols")


A_SHARE_SECURITY_MASTER_SCOPE = BackfillScope(
    scope_id="a-share:security-master",
    name="A 股全市场 Security Master",
    kind=BackfillScopeKind.SECURITY_MASTER,
)
CSI_300_SCOPE = BackfillScope(
    scope_id="index:000300",
    name="沪深 300 历史成分",
    kind=BackfillScopeKind.INDEX_UNIVERSE,
    benchmark_code="000300",
)
CSI_500_SCOPE = BackfillScope(
    scope_id="index:000905",
    name="中证 500 历史成分",
    kind=BackfillScopeKind.INDEX_UNIVERSE,
    benchmark_code="000905",
)


@dataclass(frozen=True)
class BackfillPlan:
    plan_id: str
    provider_id: str
    scopes: tuple[BackfillScope, ...]
    domains: tuple[BackfillDataDomain, ...]
    start_date: date
    end_date: date
    created_at: datetime
    output_trust_state: DataTrustState
    price_adjustment: PriceAdjustment
    provider_use: ProviderUse = ProviderUse.RAW_BULK_PERSISTENCE
    symbols: tuple[str, ...] = ()
    markets: tuple[str, ...] = ("XSHG", "XSHE", "XBSE")
    all_a_share: bool = False

    def __post_init__(self) -> None:
        _required(self.plan_id, "plan_id")
        _required(self.provider_id, "provider_id")
        object.__setattr__(self, "scopes", tuple(self.scopes))
        object.__setattr__(
            self,
            "domains",
            tuple(BackfillDataDomain(item) for item in self.domains),
        )
        if not self.scopes:
            raise ValueError("backfill plan requires at least one scope")
        if not self.domains:
            raise ValueError("backfill plan requires at least one data domain")
        scope_ids = tuple(scope.scope_id for scope in self.scopes)
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("backfill scopes must be unique")
        if len(self.domains) != len(set(self.domains)):
            raise ValueError("backfill data domains must be unique")
        object.__setattr__(self, "provider_use", ProviderUse(self.provider_use))
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "markets", tuple(self.markets))
        if type(self.all_a_share) is not bool:
            raise TypeError("all_a_share must be a boolean")
        if self.all_a_share and self.symbols:
            raise ValueError("all_a_share and explicit symbols are mutually exclusive")
        if self.all_a_share and self.provider_use is not ProviderUse.PRIVATE_LOCAL_RESEARCH:
            raise ValueError("all_a_share is restricted to private_local_research")
        if len(self.symbols) != len(set(self.symbols)):
            raise ValueError("backfill symbols must be unique")
        for symbol in self.symbols:
            if _A_SHARE_SYMBOL.fullmatch(symbol) is None:
                raise ValueError("backfill symbols must use SH.000000, SZ.000000, or BJ.000000")
        if not self.markets or len(self.markets) != len(set(self.markets)):
            raise ValueError("backfill markets must be non-empty and unique")
        if any(market not in _MARKETS for market in self.markets):
            raise ValueError("backfill markets must be XSHG, XSHE, or XBSE")
        explicit_symbols = tuple(
            symbol
            for scope in self.scopes
            if scope.kind is BackfillScopeKind.EXPLICIT_SYMBOLS
            for symbol in scope.symbols
        )
        if explicit_symbols and set(explicit_symbols) != set(self.symbols):
            raise ValueError("plan symbols must match explicit-symbol scopes")
        _date_interval(self.start_date, self.end_date)
        _aware(self.created_at, "created_at")
        object.__setattr__(self, "output_trust_state", DataTrustState(self.output_trust_state))
        try:
            adjustment = PriceAdjustment(self.price_adjustment)
        except ValueError as error:
            raise ValueError("backfill prices must be raw and unadjusted") from error
        object.__setattr__(self, "price_adjustment", adjustment)
        if (
            BackfillDataDomain.RAW_DAILY_BAR in self.domains
            and adjustment is not PriceAdjustment.UNADJUSTED
        ):
            raise ValueError("backfill prices must be raw and unadjusted")
        if (
            self.provider_use is ProviderUse.PRIVATE_LOCAL_RESEARCH
            and self.output_trust_state is not DataTrustState.NORMALIZED_CURRENT
        ):
            raise ValueError("private local research backfills must remain normalized_current")


@dataclass(frozen=True)
class BackfillWorkUnit:
    plan_id: str
    checkpoint_key: str
    scope_id: str
    domain: BackfillDataDomain
    market: str | None
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        _required(self.plan_id, "plan_id")
        _required(self.checkpoint_key, "checkpoint_key")
        _required(self.scope_id, "scope_id")
        object.__setattr__(self, "domain", BackfillDataDomain(self.domain))
        if self.market is not None:
            _required(self.market, "market")
        _date_interval(self.start_date, self.end_date)


@dataclass(frozen=True)
class BackfillQualification:
    provider_id: str
    permitted: bool
    evaluated_at: datetime
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(self.provider_id, "provider_id")
        if type(self.permitted) is not bool:
            raise TypeError("permitted must be a boolean")
        _aware(self.evaluated_at, "evaluated_at")
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        for item in (*self.blockers, *self.warnings):
            _required(item, "qualification message")
        if self.permitted == bool(self.blockers):
            raise ValueError("permitted qualification and blockers are inconsistent")


@dataclass(frozen=True)
class ProviderRetrievalMetadata:
    provider_id: str
    retrieved_at: datetime
    cutoff_date: date | None
    adjustment_mode: str
    units: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(self.provider_id, "provider_id")
        _aware(self.retrieved_at, "retrieved_at")
        if self.cutoff_date is not None and not isinstance(self.cutoff_date, date):
            raise TypeError("cutoff_date must be a date")
        _required(self.adjustment_mode, "adjustment_mode")
        object.__setattr__(self, "units", tuple(tuple(item) for item in self.units))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if len({name for name, _unit in self.units}) != len(self.units):
            raise ValueError("provider metadata units must be unique")
        for name, unit in self.units:
            _required(name, "unit field")
            _required(unit, "unit")
        for warning in self.warnings:
            _required(warning, "warning")


@dataclass(frozen=True)
class BackfillBatch:
    """A normalized/staged batch whose payload remains behind adapter ports."""

    work_unit: BackfillWorkUnit
    metadata: ProviderRetrievalMetadata
    row_count: int
    rejected_rows: int
    content_hash: str
    expected_rows: int | None
    trust_state: DataTrustState
    quality_status: DatasetQualityStatus
    issue_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]
    payload: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.work_unit, BackfillWorkUnit):
            raise TypeError("work_unit must be a BackfillWorkUnit")
        if not isinstance(self.metadata, ProviderRetrievalMetadata):
            raise TypeError("metadata must be ProviderRetrievalMetadata")
        for value, field_name in (
            (self.row_count, "row_count"),
            (self.rejected_rows, "rejected_rows"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.expected_rows is not None and (
            type(self.expected_rows) is not int or self.expected_rows < 0
        ):
            raise ValueError("expected_rows must be a non-negative integer or None")
        if _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")
        object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        object.__setattr__(self, "quality_status", DatasetQualityStatus(self.quality_status))
        object.__setattr__(self, "issue_counts", tuple(self.issue_counts))
        object.__setattr__(self, "warnings", tuple(self.warnings))
        for code, count in self.issue_counts:
            _required(code, "quality issue code")
            if type(count) is not int or count < 0:
                raise ValueError("quality issue counts must be non-negative integers")
        for warning in self.warnings:
            _required(warning, "batch warning")


@dataclass(frozen=True)
class BackfillJob:
    job_id: str
    plan: BackfillPlan
    qualification: BackfillQualification
    status: BackfillJobStatus
    created_at: datetime
    updated_at: datetime
    dataset_version_id: str | None = None
    failure_reason: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _required(self.job_id, "job_id")
        if not isinstance(self.plan, BackfillPlan):
            raise TypeError("plan must be a BackfillPlan")
        if not isinstance(self.qualification, BackfillQualification):
            raise TypeError("qualification must be a BackfillQualification")
        object.__setattr__(self, "status", BackfillJobStatus(self.status))
        _aware(self.created_at, "created_at")
        _aware(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        object.__setattr__(self, "failure_reason", tuple(self.failure_reason))
        for reason in self.failure_reason:
            _required(reason, "failure reason")
        if self.status is BackfillJobStatus.BLOCKED and not self.failure_reason:
            raise ValueError("blocked job requires failure reasons")
        if self.status is BackfillJobStatus.FAILED and not self.failure_reason:
            raise ValueError("failed job requires failure reasons")
        if self.status is BackfillJobStatus.SUCCEEDED:
            _required(self.dataset_version_id or "", "dataset_version_id")
        elif self.dataset_version_id is not None:
            raise ValueError("dataset_version_id is only valid for a succeeded job")

    @classmethod
    def planned(
        cls,
        plan: BackfillPlan,
        qualification: BackfillQualification,
    ) -> BackfillJob:
        if not qualification.permitted:
            raise ValueError("a denied qualification cannot create a planned job")
        return cls(
            job_id=f"job:{plan.plan_id}",
            plan=plan,
            qualification=qualification,
            status=BackfillJobStatus.PLANNED,
            created_at=qualification.evaluated_at,
            updated_at=qualification.evaluated_at,
        )

    @classmethod
    def blocked(
        cls,
        plan: BackfillPlan,
        qualification: BackfillQualification,
    ) -> BackfillJob:
        if qualification.permitted:
            raise ValueError("a permitted qualification cannot create a blocked job")
        return cls(
            job_id=f"job:{plan.plan_id}",
            plan=plan,
            qualification=qualification,
            status=BackfillJobStatus.BLOCKED,
            created_at=qualification.evaluated_at,
            updated_at=qualification.evaluated_at,
            failure_reason=qualification.blockers,
        )

    def transition(
        self,
        status: BackfillJobStatus,
        *,
        at: datetime,
        dataset_version_id: str | None = None,
        failure_reason: tuple[str, ...] = (),
    ) -> BackfillJob:
        target = BackfillJobStatus(status)
        if self.status.terminal:
            raise ValueError("terminal backfill job cannot transition")
        allowed = {
            BackfillJobStatus.PLANNED: {
                BackfillJobStatus.RUNNING,
                BackfillJobStatus.BLOCKED,
                BackfillJobStatus.FAILED,
            },
            BackfillJobStatus.RUNNING: {
                BackfillJobStatus.SUCCEEDED,
                BackfillJobStatus.FAILED,
            },
            BackfillJobStatus.FAILED: {BackfillJobStatus.RUNNING},
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(f"invalid backfill job transition: {self.status.value}->{target.value}")
        return replace(
            self,
            status=target,
            updated_at=_aware(at, "transition time"),
            dataset_version_id=dataset_version_id,
            failure_reason=tuple(failure_reason),
        )


@dataclass(frozen=True)
class BackfillCheckpoint:
    job_id: str
    checkpoint_key: str
    scope_id: str
    domain: BackfillDataDomain
    market: str | None
    start_date: date
    end_date: date
    status: BackfillCheckpointStatus
    updated_at: datetime
    processed_rows: int = 0
    rejected_rows: int = 0
    content_hash: str | None = None
    cursor: str | None = None
    error: str | None = None
    retrieval_metadata: ProviderRetrievalMetadata | None = None

    def __post_init__(self) -> None:
        _required(self.job_id, "job_id")
        _required(self.checkpoint_key, "checkpoint_key")
        _required(self.scope_id, "scope_id")
        object.__setattr__(self, "domain", BackfillDataDomain(self.domain))
        if self.market is not None:
            _required(self.market, "market")
        _date_interval(self.start_date, self.end_date)
        object.__setattr__(self, "status", BackfillCheckpointStatus(self.status))
        _aware(self.updated_at, "updated_at")
        if type(self.processed_rows) is not int or self.processed_rows < 0:
            raise ValueError("processed_rows must be a non-negative integer")
        if type(self.rejected_rows) is not int or self.rejected_rows < 0:
            raise ValueError("rejected_rows must be a non-negative integer")
        if self.content_hash is not None and _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")
        if self.status is BackfillCheckpointStatus.SUCCEEDED and self.content_hash is None:
            raise ValueError("succeeded checkpoint requires content_hash")
        if self.retrieval_metadata is not None and not isinstance(
            self.retrieval_metadata,
            ProviderRetrievalMetadata,
        ):
            raise TypeError("retrieval_metadata must be ProviderRetrievalMetadata")
        if self.status is BackfillCheckpointStatus.FAILED:
            _required(self.error or "", "checkpoint error")
        elif self.error is not None:
            raise ValueError("checkpoint error is only valid for failed status")

    @classmethod
    def pending(
        cls,
        *,
        job_id: str,
        checkpoint_key: str,
        scope_id: str,
        domain: BackfillDataDomain,
        market: str | None,
        start_date: date,
        end_date: date,
        at: datetime,
    ) -> BackfillCheckpoint:
        return cls(
            job_id=job_id,
            checkpoint_key=checkpoint_key,
            scope_id=scope_id,
            domain=domain,
            market=market,
            start_date=start_date,
            end_date=end_date,
            status=BackfillCheckpointStatus.PENDING,
            updated_at=at,
        )

    def transition(
        self,
        status: BackfillCheckpointStatus,
        *,
        at: datetime,
        processed_rows: int = 0,
        rejected_rows: int = 0,
        content_hash: str | None = None,
        cursor: str | None = None,
        error: str | None = None,
        retrieval_metadata: ProviderRetrievalMetadata | None = None,
    ) -> BackfillCheckpoint:
        target = BackfillCheckpointStatus(status)
        if self.status.terminal:
            raise ValueError("terminal checkpoint cannot transition")
        allowed = {
            BackfillCheckpointStatus.PENDING: {
                BackfillCheckpointStatus.RUNNING,
                BackfillCheckpointStatus.FAILED,
            },
            BackfillCheckpointStatus.RUNNING: {
                BackfillCheckpointStatus.SUCCEEDED,
                BackfillCheckpointStatus.FAILED,
            },
            BackfillCheckpointStatus.FAILED: {BackfillCheckpointStatus.RUNNING},
        }
        if target not in allowed.get(self.status, set()):
            raise ValueError(
                f"invalid checkpoint transition: {self.status.value}->{target.value}"
            )
        return replace(
            self,
            status=target,
            updated_at=_aware(at, "transition time"),
            processed_rows=processed_rows,
            rejected_rows=rejected_rows,
            content_hash=content_hash,
            cursor=cursor,
            error=error,
            retrieval_metadata=retrieval_metadata,
        )


@dataclass(frozen=True)
class DatasetQualityReport:
    report_id: str
    dataset_version_id: str
    job_id: str
    status: DatasetQualityStatus
    created_at: datetime
    checks_passed: int
    checks_failed: int
    issue_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _required(self.report_id, "report_id")
        _required(self.dataset_version_id, "dataset_version_id")
        _required(self.job_id, "job_id")
        object.__setattr__(self, "status", DatasetQualityStatus(self.status))
        _aware(self.created_at, "created_at")
        for value in (self.checks_passed, self.checks_failed):
            if type(value) is not int or value < 0:
                raise ValueError("quality check counts must be non-negative integers")
        object.__setattr__(self, "issue_counts", tuple(self.issue_counts))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class DatasetCoverageReport:
    report_id: str
    dataset_version_id: str
    job_id: str
    scope_id: str
    domain: BackfillDataDomain
    start_date: date
    end_date: date
    expected_rows: int | None
    observed_rows: int
    coverage_ratio: float | None
    created_at: datetime
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.report_id, "report_id"),
            (self.dataset_version_id, "dataset_version_id"),
            (self.job_id, "job_id"),
            (self.scope_id, "scope_id"),
        ):
            _required(value, field_name)
        object.__setattr__(self, "domain", BackfillDataDomain(self.domain))
        _date_interval(self.start_date, self.end_date)
        if self.expected_rows is not None and (
            type(self.expected_rows) is not int or self.expected_rows < 0
        ):
            raise ValueError("expected_rows must be a non-negative integer or None")
        if type(self.observed_rows) is not int or self.observed_rows < 0:
            raise ValueError("observed_rows must be a non-negative integer")
        if self.coverage_ratio is not None and not 0 <= self.coverage_ratio <= 1:
            raise ValueError("coverage_ratio must be between 0 and 1")
        _aware(self.created_at, "created_at")
        object.__setattr__(self, "warnings", tuple(self.warnings))
