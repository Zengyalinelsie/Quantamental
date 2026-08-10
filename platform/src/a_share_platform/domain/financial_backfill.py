"""Provider-neutral contracts for checkpointed A-share financial backfills."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from .backfill import BackfillDataDomain, DatasetQualityStatus
from .disclosure import RawObject, RetentionPolicy
from .financial_sources import ProviderFinancialRow
from .metrics import MetricUnit, StatementType
from .pit import DataTrustState
from .run_context import DataMode

_CANONICAL_SYMBOL = re.compile(r"^(SH|SZ)\.\d{6}$")
_PROVIDER_TABLE = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _plain_date(value: date, field_name: str) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a date")
    return value


class FinancialBackfillCohort(str, Enum):
    """Ordered scale-up cohorts; CSI500 is not executable before CSI300 coverage."""

    CSI_300 = "csi300"
    CSI_500 = "csi500"

    @property
    def benchmark_id(self) -> str:
        return {
            self.CSI_300: "index:000300",
            self.CSI_500: "index:000905",
        }[self]


@dataclass(frozen=True)
class FinancialStatementSelection:
    """One canonical statement and its explicitly named provider table."""

    statement_type: StatementType
    provider_table: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        _text(self.provider_table, "provider_table")
        if _PROVIDER_TABLE.fullmatch(self.provider_table) is None:
            raise ValueError("provider_table must use lowercase snake_case")


@dataclass(frozen=True)
class FinancialBackfillPlan:
    """Immutable bulk plan bound to one qualified profile and frozen universe."""

    plan_id: str
    provider_id: str
    provider_profile_version: str
    cohort: FinancialBackfillCohort
    universe_version_id: str
    mapping_version_id: str
    statements: tuple[FinancialStatementSelection, ...]
    report_period_ends: tuple[date, ...]
    symbols: tuple[str, ...]
    symbol_bucket_size: int
    created_at: datetime
    data_mode: DataMode
    output_trust_state: DataTrustState
    allow_read_through_cache: bool
    bulk_persistence_acknowledged: bool
    predecessor_coverage_report_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "plan_id",
            "provider_id",
            "provider_profile_version",
            "universe_version_id",
            "mapping_version_id",
        ):
            _text(getattr(self, field_name), field_name)

        cohort = FinancialBackfillCohort(self.cohort)
        object.__setattr__(self, "cohort", cohort)
        data_mode = DataMode(self.data_mode)
        trust = DataTrustState(self.output_trust_state)
        object.__setattr__(self, "data_mode", data_mode)
        object.__setattr__(self, "output_trust_state", trust)
        if data_mode is not DataMode.CURRENT_RESEARCH:
            raise ValueError("financial scale-up plans must use current_research")
        if trust is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("financial scale-up plans must remain normalized_current")

        if type(self.allow_read_through_cache) is not bool:
            raise TypeError("allow_read_through_cache must be a boolean")
        if type(self.bulk_persistence_acknowledged) is not bool:
            raise TypeError("bulk_persistence_acknowledged must be a boolean")
        if type(self.symbol_bucket_size) is not int or self.symbol_bucket_size <= 0:
            raise ValueError("symbol_bucket_size must be a positive integer")
        _aware(self.created_at, "created_at")

        statements = tuple(self.statements)
        if not statements or not all(
            isinstance(item, FinancialStatementSelection) for item in statements
        ):
            raise ValueError("statements must contain FinancialStatementSelection values")
        statement_types = tuple(item.statement_type for item in statements)
        provider_tables = tuple(item.provider_table for item in statements)
        if len(statement_types) != len(set(statement_types)):
            raise ValueError("statement types must be unique")
        if len(provider_tables) != len(set(provider_tables)):
            raise ValueError("provider tables must be unique")
        object.__setattr__(
            self,
            "statements",
            tuple(sorted(statements, key=lambda item: item.statement_type.value)),
        )

        report_periods = tuple(self.report_period_ends)
        if not report_periods:
            raise ValueError("report_period_ends must not be empty")
        for period in report_periods:
            _plain_date(period, "report_period_end")
        if len(report_periods) != len(set(report_periods)):
            raise ValueError("report_period_ends must be unique")
        object.__setattr__(self, "report_period_ends", tuple(sorted(report_periods)))

        symbols = tuple(self.symbols)
        if not symbols:
            raise ValueError("symbols must not be empty")
        if len(symbols) != len(set(symbols)):
            raise ValueError("symbols must be unique")
        if any(_CANONICAL_SYMBOL.fullmatch(symbol) is None for symbol in symbols):
            raise ValueError("symbols must use canonical SH.000000 or SZ.000000 form")
        object.__setattr__(self, "symbols", tuple(sorted(symbols)))

        predecessor = self.predecessor_coverage_report_id
        if cohort is FinancialBackfillCohort.CSI_500:
            _text(predecessor or "", "CSI300 coverage predecessor")
        elif predecessor is not None:
            _text(predecessor, "predecessor_coverage_report_id")

    @property
    def benchmark_id(self) -> str:
        return self.cohort.benchmark_id


@dataclass(frozen=True)
class FinancialBackfillWorkUnit:
    """Atomic provider/table/report-period/symbol-bucket retrieval unit."""

    plan_id: str
    checkpoint_key: str
    provider_id: str
    provider_profile_version: str
    benchmark_id: str
    universe_version_id: str
    mapping_version_id: str
    statement_type: StatementType
    provider_table: str
    report_period_end: date
    symbol_bucket_id: str
    symbols: tuple[str, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "plan_id",
            "checkpoint_key",
            "provider_id",
            "provider_profile_version",
            "benchmark_id",
            "universe_version_id",
            "mapping_version_id",
            "symbol_bucket_id",
        ):
            _text(getattr(self, field_name), field_name)
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        if _PROVIDER_TABLE.fullmatch(self.provider_table) is None:
            raise ValueError("provider_table must use lowercase snake_case")
        _plain_date(self.report_period_end, "report_period_end")
        symbols = tuple(self.symbols)
        if not symbols or len(symbols) != len(set(symbols)):
            raise ValueError("work-unit symbols must be non-empty and unique")
        if any(_CANONICAL_SYMBOL.fullmatch(symbol) is None for symbol in symbols):
            raise ValueError("work-unit symbols must use canonical A-share identifiers")
        object.__setattr__(self, "symbols", tuple(sorted(symbols)))

    @property
    def domain(self) -> BackfillDataDomain:
        return BackfillDataDomain.FINANCIAL_STATEMENT


@dataclass(frozen=True)
class FinancialBackfillBatchResult:
    """Provider-neutral counts and provenance used to close one work unit."""

    work_unit: FinancialBackfillWorkUnit
    retrieved_at: datetime
    provider_cutoff_date: date
    content_hash: str
    processed_provider_rows: int
    canonical_observations: int
    rejected_rows: int
    accepted_symbols: tuple[str, ...]
    quality_status: DatasetQualityStatus
    issue_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.work_unit, FinancialBackfillWorkUnit):
            raise TypeError("work_unit must be a FinancialBackfillWorkUnit")
        retrieved_at = _aware(self.retrieved_at, "retrieved_at")
        cutoff = _plain_date(self.provider_cutoff_date, "provider_cutoff_date")
        if cutoff > retrieved_at.date():
            raise ValueError("provider_cutoff_date cannot follow retrieved_at")
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")
        for value, field_name in (
            (self.processed_provider_rows, "processed_provider_rows"),
            (self.canonical_observations, "canonical_observations"),
            (self.rejected_rows, "rejected_rows"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.rejected_rows > self.processed_provider_rows:
            raise ValueError("rejected_rows cannot exceed processed_provider_rows")

        accepted = tuple(self.accepted_symbols)
        if len(accepted) != len(set(accepted)):
            raise ValueError("accepted_symbols must be unique")
        if not set(accepted).issubset(self.work_unit.symbols):
            raise ValueError("accepted_symbols must belong to the work unit")
        object.__setattr__(self, "accepted_symbols", tuple(sorted(accepted)))
        status = DatasetQualityStatus(self.quality_status)
        object.__setattr__(self, "quality_status", status)

        issues = tuple(self.issue_counts)
        for code, count in issues:
            _text(code, "quality issue code")
            if type(count) is not int or count < 0:
                raise ValueError("quality issue counts must be non-negative integers")
        if status is DatasetQualityStatus.FAILED and not any(count for _, count in issues):
            raise ValueError("failed quality result requires at least one issue")
        object.__setattr__(self, "issue_counts", issues)
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True)
class FinancialProviderBatch:
    """One evidence-bound staged provider batch; values remain provider rows."""

    work_unit: FinancialBackfillWorkUnit
    evidence: RawObject
    rows: tuple[ProviderFinancialRow, ...]
    provider_record_count: int
    missing_value_count: int
    accepted_symbols: tuple[str, ...]
    trust_state: DataTrustState
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.work_unit, FinancialBackfillWorkUnit):
            raise TypeError("work_unit must be a FinancialBackfillWorkUnit")
        if not isinstance(self.evidence, RawObject):
            raise TypeError("evidence must be a RawObject")
        if self.evidence.provider_id != self.work_unit.provider_id:
            raise ValueError("evidence provider does not match financial work unit")
        if self.evidence.retention_policy is RetentionPolicy.METADATA_ONLY:
            raise ValueError("financial provider rows require retained response evidence")
        rows = tuple(self.rows)
        for row in rows:
            if not isinstance(row, ProviderFinancialRow):
                raise TypeError("rows must contain ProviderFinancialRow values")
            if row.provider_id != self.work_unit.provider_id:
                raise ValueError("provider row provider does not match work unit")
            if row.provider_table != self.work_unit.provider_table:
                raise ValueError("provider row table does not match work unit")
            if row.statement_type is not self.work_unit.statement_type:
                raise ValueError("provider row statement does not match work unit")
            if row.report_period_end != self.work_unit.report_period_end:
                raise ValueError("provider row report period does not match work unit")
            if (row.raw_object_id, row.raw_object_hash) != (
                self.evidence.raw_object_id,
                self.evidence.content_hash,
            ):
                raise ValueError("provider row evidence does not match batch evidence")
        row_ids = tuple(row.row_id for row in rows)
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("provider batch row identifiers must be unique")
        object.__setattr__(self, "rows", rows)
        for value, field_name in (
            (self.provider_record_count, "provider_record_count"),
            (self.missing_value_count, "missing_value_count"),
        ):
            if type(value) is not int or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        provider_record_ids = {row.provider_record_id for row in rows}
        if len(provider_record_ids) > self.provider_record_count:
            raise ValueError("provider rows exceed the declared provider record count")
        accepted = tuple(self.accepted_symbols)
        if len(accepted) != len(set(accepted)):
            raise ValueError("accepted_symbols must be unique")
        if not set(accepted).issubset(self.work_unit.symbols):
            raise ValueError("accepted_symbols must belong to the work unit")
        if len(accepted) > self.provider_record_count:
            raise ValueError("accepted symbols cannot exceed provider record count")
        object.__setattr__(self, "accepted_symbols", tuple(sorted(accepted)))
        trust = DataTrustState(self.trust_state)
        if trust is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("financial provider batch must remain normalized_current")
        object.__setattr__(self, "trust_state", trust)
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)

    @property
    def content_hash(self) -> str:
        return self.evidence.content_hash

    @property
    def raw_object_id(self) -> str:
        return self.evidence.raw_object_id

    @property
    def retrieved_at(self) -> datetime:
        return self.evidence.retrieved_at


@dataclass(frozen=True)
class MappedFinancialRow:
    """Canonical Decimal value that still preserves its full provider observation."""

    mapped_row_id: str
    source_row: ProviderFinancialRow
    mapping_id: str
    mapping_version_id: str
    metric_code: str
    value: Decimal
    unit: MetricUnit
    currency: str | None
    trust_state: DataTrustState

    def __post_init__(self) -> None:
        for field_name in (
            "mapped_row_id",
            "mapping_id",
            "mapping_version_id",
            "metric_code",
        ):
            _text(getattr(self, field_name), field_name)
        if not isinstance(self.source_row, ProviderFinancialRow):
            raise TypeError("source_row must be a ProviderFinancialRow")
        if not isinstance(self.value, Decimal):
            raise TypeError("mapped financial value must use Decimal")
        if not self.value.is_finite():
            raise ValueError("mapped financial value must be finite")
        object.__setattr__(self, "unit", MetricUnit(self.unit))
        trust = DataTrustState(self.trust_state)
        if trust is not DataTrustState.NORMALIZED_CURRENT:
            raise ValueError("mapped provider financial rows remain normalized_current")
        object.__setattr__(self, "trust_state", trust)

    @property
    def provider_id(self) -> str:
        return self.source_row.provider_id

    @property
    def statement_type(self) -> StatementType:
        return self.source_row.statement_type

    @property
    def raw_object_id(self) -> str:
        return self.source_row.raw_object_id

    @property
    def raw_object_hash(self) -> str:
        return self.source_row.raw_object_hash


@dataclass(frozen=True)
class FinancialMappingResult:
    provider_batch: FinancialProviderBatch
    mapped_rows: tuple[MappedFinancialRow, ...]
    unmapped_row_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.provider_batch, FinancialProviderBatch):
            raise TypeError("provider_batch must be a FinancialProviderBatch")
        mapped = tuple(self.mapped_rows)
        source_ids = {row.row_id for row in self.provider_batch.rows}
        if any(row.source_row.row_id not in source_ids for row in mapped):
            raise ValueError("mapped rows must originate from the provider batch")
        mapped_ids = tuple(row.mapped_row_id for row in mapped)
        if len(mapped_ids) != len(set(mapped_ids)):
            raise ValueError("mapped financial row identifiers must be unique")
        if any(
            row.mapping_version_id != self.provider_batch.work_unit.mapping_version_id
            or row.provider_id != self.provider_batch.work_unit.provider_id
            or row.trust_state is not self.provider_batch.trust_state
            for row in mapped
        ):
            raise ValueError("mapped rows do not match the immutable provider batch")
        object.__setattr__(self, "mapped_rows", mapped)
        unmapped = tuple(self.unmapped_row_ids)
        if len(unmapped) != len(set(unmapped)) or not set(unmapped).issubset(source_ids):
            raise ValueError("unmapped_row_ids must be unique provider batch rows")
        if set(unmapped).intersection(row.source_row.row_id for row in mapped):
            raise ValueError("one provider row cannot be both mapped and unmapped")
        mapped_source_ids = tuple(row.source_row.row_id for row in mapped)
        if len(mapped_source_ids) != len(set(mapped_source_ids)):
            raise ValueError("one provider row cannot produce multiple direct mappings")
        if set(mapped_source_ids).union(unmapped) != source_ids:
            raise ValueError("every provider row must be classified as mapped or unmapped")
        object.__setattr__(self, "unmapped_row_ids", unmapped)
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True)
class FinancialPersistResult:
    dataset_version_id: str
    observation_ids: tuple[str, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.dataset_version_id, "dataset_version_id")
        observations = tuple(self.observation_ids)
        if not observations or len(observations) != len(set(observations)):
            raise ValueError("observation_ids must be non-empty and unique")
        for observation_id in observations:
            _text(observation_id, "observation_id")
        object.__setattr__(self, "observation_ids", observations)
        warnings = tuple(self.warnings)
        for warning in warnings:
            _text(warning, "warning")
        object.__setattr__(self, "warnings", warnings)
