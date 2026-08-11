"""AkShare/Eastmoney financial-statement fallback with conservative timing.

AkShare data frames are web-derived current observations.  Date-only NOTICE_DATE
and UPDATE_DATE fields are retained in raw evidence and warnings, but never
promoted to exact market-availability timestamps.  Every staged value therefore
uses retrieval time conservatively and remains ``normalized_current``.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from functools import partial
from typing import Protocol

from a_share_platform.domain.disclosure import RawObject
from a_share_platform.domain.financial_backfill import (
    FinancialBackfillWorkUnit,
    FinancialProviderBatch,
)
from a_share_platform.domain.financial_sources import (
    AvailabilityMethod,
    FinancialStatementScope,
    FinancialValueBasis,
    ProviderFinancialRow,
    ReportVersionType,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType
from a_share_platform.ports.financial_backfill import FinancialEvidenceCapture

_REQUESTED_SYMBOL_FIELD = "__a_share_platform_requested_symbol"
_REPORT_DATE_FIELD = "REPORT_DATE"
_SECURITY_CODE_FIELD = "SECURITY_CODE"
_NOTICE_DATE_FIELD = "NOTICE_DATE"
_UPDATE_DATE_FIELD = "UPDATE_DATE"
_MISSING_TEXT = frozenset({"", "-", "--", "nan", "nat", "none", "null"})


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class AkShareFinancialClient(Protocol):
    def stock_balance_sheet_by_report_em(self, *, symbol: str) -> object: ...

    def stock_profit_sheet_by_report_em(self, *, symbol: str) -> object: ...

    def stock_cash_flow_sheet_by_report_em(self, *, symbol: str) -> object: ...


class AkShareRequestExecutor(Protocol):
    """Provider-edge boundary for throttling and bounded retry policy."""

    def execute(self, operation: str, action: Callable[[], object]) -> object: ...


class AkShareEndpoint(str, Enum):
    BALANCE_SHEET = "stock_balance_sheet_by_report_em"
    INCOME_STATEMENT = "stock_profit_sheet_by_report_em"
    CASH_FLOW_STATEMENT = "stock_cash_flow_sheet_by_report_em"


@dataclass(frozen=True)
class AkShareFinancialSnapshotKey:
    """Source-aware identity for one all-period Eastmoney response."""

    provider_id: str
    endpoint: AkShareEndpoint
    canonical_symbol: str

    def __post_init__(self) -> None:
        _text(self.provider_id, "provider_id")
        object.__setattr__(self, "endpoint", AkShareEndpoint(self.endpoint))
        AkShareFinancialNormalizer._canonical_symbol(self.canonical_symbol)


@dataclass(frozen=True)
class AkShareFinancialSnapshot:
    """Immutable, replayable records from one provider request.

    Eastmoney's financial endpoints return every available report period for a
    symbol.  Keeping tuple-encoded record items prevents later period work units
    or evidence sinks from mutating the cached observation in place.
    """

    key: AkShareFinancialSnapshotKey
    record_items: tuple[tuple[tuple[str, object], ...], ...]
    retrieved_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.key, AkShareFinancialSnapshotKey):
            raise TypeError("key must be an AkShareFinancialSnapshotKey")
        if not isinstance(self.record_items, tuple):
            raise TypeError("record_items must be a tuple")
        for record in self.record_items:
            if not isinstance(record, tuple):
                raise TypeError("cached AkShare records must be tuples")
            names = tuple(name for name, _value in record)
            if any(not isinstance(name, str) or not name for name in names):
                raise ValueError("cached AkShare field names must be non-empty strings")
            if len(names) != len(set(names)):
                raise ValueError("cached AkShare record field names must be unique")
            if any(
                value is not None and not isinstance(value, (str, int, float, bool, Decimal))
                for _name, value in record
            ):
                raise TypeError("cached AkShare values must be immutable scalars")
        if (
            not isinstance(self.retrieved_at, datetime)
            or self.retrieved_at.tzinfo is None
            or self.retrieved_at.utcoffset() is None
        ):
            raise ValueError("retrieved_at must be timezone-aware")

    @classmethod
    def from_provider_records(
        cls,
        *,
        key: AkShareFinancialSnapshotKey,
        provider_records: tuple[Mapping[str, object], ...],
        retrieved_at: datetime,
    ) -> AkShareFinancialSnapshot:
        return cls(
            key=key,
            record_items=tuple(tuple(record.items()) for record in provider_records),
            retrieved_at=retrieved_at,
        )

    def materialize(self) -> tuple[Mapping[str, object], ...]:
        """Return defensive mappings while retaining immutable cached storage."""

        return tuple(dict(record) for record in self.record_items)


class AkShareFinancialSnapshotCache(Protocol):
    def get(
        self,
        key: AkShareFinancialSnapshotKey,
    ) -> AkShareFinancialSnapshot | None: ...

    def put(self, snapshot: AkShareFinancialSnapshot) -> None: ...


class AkShareInMemoryFinancialSnapshotCache:
    """Run-scoped cache; callers must use a single sequential source instance."""

    def __init__(self) -> None:
        self._snapshots: dict[
            AkShareFinancialSnapshotKey,
            AkShareFinancialSnapshot,
        ] = {}

    def get(
        self,
        key: AkShareFinancialSnapshotKey,
    ) -> AkShareFinancialSnapshot | None:
        if not isinstance(key, AkShareFinancialSnapshotKey):
            raise TypeError("key must be an AkShareFinancialSnapshotKey")
        return self._snapshots.get(key)

    def put(self, snapshot: AkShareFinancialSnapshot) -> None:
        if not isinstance(snapshot, AkShareFinancialSnapshot):
            raise TypeError("snapshot must be an AkShareFinancialSnapshot")
        existing = self._snapshots.get(snapshot.key)
        if existing is not None and existing != snapshot:
            raise ValueError("conflicting AkShare snapshot for the same source key")
        self._snapshots[snapshot.key] = snapshot


_ENDPOINTS = {
    StatementType.BALANCE_SHEET: ("balance_sheet", AkShareEndpoint.BALANCE_SHEET),
    StatementType.INCOME_STATEMENT: ("income_statement", AkShareEndpoint.INCOME_STATEMENT),
    StatementType.CASH_FLOW_STATEMENT: ("cash_flow", AkShareEndpoint.CASH_FLOW_STATEMENT),
}


@dataclass(frozen=True)
class AkShareFieldContract:
    provider_field: str
    provider_unit: str
    scale_to_canonical: Decimal
    currency: str | None
    statement_scope: FinancialStatementScope
    value_basis: FinancialValueBasis

    def __post_init__(self) -> None:
        _text(self.provider_field, "provider_field")
        if self.provider_field in {
            _REQUESTED_SYMBOL_FIELD,
            _REPORT_DATE_FIELD,
            _SECURITY_CODE_FIELD,
            _NOTICE_DATE_FIELD,
            _UPDATE_DATE_FIELD,
        }:
            raise ValueError("provider_field is reserved for AkShare record identity")
        _text(self.provider_unit, "provider_unit")
        if not isinstance(self.scale_to_canonical, Decimal):
            raise TypeError("scale_to_canonical must use Decimal")
        if not self.scale_to_canonical.is_finite() or self.scale_to_canonical == 0:
            raise ValueError("scale_to_canonical must be finite and non-zero")
        if self.currency is not None:
            _text(self.currency, "currency")
        object.__setattr__(
            self,
            "statement_scope",
            FinancialStatementScope(self.statement_scope),
        )
        object.__setattr__(self, "value_basis", FinancialValueBasis(self.value_basis))


class AkShareFinancialNormalizer:
    def __init__(self, fields: tuple[AkShareFieldContract, ...]) -> None:
        self._fields = tuple(fields)
        if not self._fields:
            raise ValueError("AkShare normalizer requires at least one field contract")
        if any(not isinstance(field, AkShareFieldContract) for field in self._fields):
            raise TypeError("fields must contain AkShareFieldContract values")
        names = tuple(field.provider_field for field in self._fields)
        if len(names) != len(set(names)):
            raise ValueError("AkShare field contracts must be unique")

    @property
    def provider_fields(self) -> tuple[str, ...]:
        return tuple(field.provider_field for field in self._fields)

    def normalize(
        self,
        *,
        work_unit: FinancialBackfillWorkUnit,
        provider_records: tuple[Mapping[str, object], ...],
        evidence: RawObject,
        retrieved_at: datetime,
    ) -> FinancialProviderBatch:
        if evidence.provider_id != work_unit.provider_id:
            raise ValueError("evidence provider does not match work unit")
        if evidence.retrieved_at != retrieved_at:
            raise ValueError("evidence retrieval time does not match normalization time")

        rows: list[ProviderFinancialRow] = []
        accepted_symbols: set[str] = set()
        seen_records: set[tuple[str, date]] = set()
        missing_values = 0
        selected_record_count = 0
        rows_outside_period = 0
        for provider_record in provider_records:
            requested_symbol = self._canonical_symbol(provider_record.get(_REQUESTED_SYMBOL_FIELD))
            if requested_symbol not in work_unit.symbols:
                raise ValueError("AkShare requested symbol is outside the work unit")
            source_code = self._source_code(provider_record.get(_SECURITY_CODE_FIELD))
            if source_code != requested_symbol.split(".", 1)[1]:
                raise ValueError("AkShare response code does not match requested symbol")
            response_period = self._provider_date(
                provider_record.get(_REPORT_DATE_FIELD),
                _REPORT_DATE_FIELD,
            )
            period_type = self._period_type(response_period)
            if response_period != work_unit.report_period_end:
                rows_outside_period += 1
                continue
            record_key = (requested_symbol, response_period)
            if record_key in seen_records:
                raise ValueError("duplicate AkShare provider record")
            seen_records.add(record_key)
            selected_record_count += 1
            notice_date = self._optional_provider_date(
                provider_record.get(_NOTICE_DATE_FIELD),
                _NOTICE_DATE_FIELD,
            )
            update_date = self._optional_provider_date(
                provider_record.get(_UPDATE_DATE_FIELD),
                _UPDATE_DATE_FIELD,
            )
            record_digest = hashlib.sha256(
                (
                    f"{work_unit.provider_id}|{work_unit.provider_table}|{requested_symbol}|"
                    f"{response_period.isoformat()}|{evidence.content_hash}"
                ).encode()
            ).hexdigest()[:24]
            provider_record_id = f"akshare-eastmoney-row:{record_digest}"
            record_had_value = False
            for field in self._fields:
                raw_value = provider_record.get(field.provider_field)
                if self._is_missing(raw_value):
                    missing_values += 1
                    continue
                numeric, conversion_warning = self._numeric(raw_value, field.provider_field)
                field_digest = hashlib.sha256(
                    f"{provider_record_id}|{field.provider_field}".encode()
                ).hexdigest()[:24]
                warnings = [
                    "AkShare/Eastmoney value is normalized_current fallback data",
                    "provider revision semantics are unavailable",
                    (
                        "provider field is not a canonical metric and requires explicit "
                        "mapping before cross-source comparison"
                    ),
                ]
                if notice_date is not None:
                    warnings.append(
                        f"NOTICE_DATE is date-only ({notice_date.isoformat()}); "
                        "not used as exact available_at"
                    )
                if update_date is not None:
                    warnings.append(
                        f"UPDATE_DATE is date-only ({update_date.isoformat()}); "
                        "not used as exact provider_updated_at"
                    )
                if field.statement_scope is FinancialStatementScope.UNKNOWN:
                    warnings.append("financial statement scope is unavailable")
                if conversion_warning is not None:
                    warnings.append(conversion_warning)
                rows.append(
                    ProviderFinancialRow(
                        row_id=f"provider-financial-row:{field_digest}",
                        provider_id=work_unit.provider_id,
                        provider_table=work_unit.provider_table,
                        provider_record_id=provider_record_id,
                        provider_field=field.provider_field,
                        market=("XSHG" if requested_symbol.startswith("SH.") else "XSHE"),
                        source_symbol=source_code,
                        statement_type=work_unit.statement_type,
                        statement_scope=field.statement_scope,
                        report_period_start=self._period_start(
                            response_period,
                            field.value_basis,
                        ),
                        report_period_end=response_period,
                        period_type=period_type,
                        value_basis=field.value_basis,
                        raw_value=numeric,
                        provider_unit=field.provider_unit,
                        scale_to_canonical=field.scale_to_canonical,
                        currency=field.currency,
                        report_version_type=ReportVersionType.UNKNOWN,
                        revision_sequence=0,
                        announced_at=None,
                        available_at=retrieved_at,
                        availability_method=AvailabilityMethod.CONSERVATIVE_RETRIEVAL_TIME,
                        provider_updated_at=None,
                        retrieved_at=retrieved_at,
                        raw_object_id=evidence.raw_object_id,
                        raw_object_hash=evidence.content_hash,
                        source_url=evidence.source_url,
                        warnings=tuple(warnings),
                    )
                )
                record_had_value = True
            if record_had_value:
                accepted_symbols.add(requested_symbol)

        batch_warnings = [
            "AkShare/Eastmoney rows are normalized_current and not strict-historical evidence",
            "date-only announcement/update fields do not establish exact availability",
        ]
        if missing_values:
            batch_warnings.append(f"missing_provider_value_count={missing_values}")
        if rows_outside_period:
            batch_warnings.append(f"provider_rows_outside_requested_period={rows_outside_period}")
        return FinancialProviderBatch(
            work_unit=work_unit,
            evidence=evidence,
            rows=tuple(rows),
            provider_record_count=selected_record_count,
            missing_value_count=missing_values,
            accepted_symbols=tuple(sorted(accepted_symbols)),
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            warnings=tuple(batch_warnings),
        )

    @staticmethod
    def _canonical_symbol(value: object) -> str:
        if (
            not isinstance(value, str)
            or len(value) != 9
            or value[:3] not in {"SH.", "SZ."}
            or not value[3:].isdigit()
        ):
            raise ValueError("AkShare requested symbol must use canonical SH./SZ. form")
        return value

    @staticmethod
    def _source_code(value: object) -> str:
        if not isinstance(value, str) or len(value) != 6 or not value.isdigit():
            raise ValueError("AkShare SECURITY_CODE must contain six digits")
        return value

    @classmethod
    def _provider_date(cls, value: object, field_name: str) -> date:
        plain = cls._plain_scalar(value)
        if isinstance(plain, datetime):
            return plain.date()
        if isinstance(plain, date):
            return plain
        if not isinstance(plain, str) or plain.strip().lower() in _MISSING_TEXT:
            raise ValueError(f"AkShare {field_name} must contain a provider date")
        text = plain.strip()
        try:
            return date.fromisoformat(text)
        except ValueError:
            try:
                return datetime.fromisoformat(text).date()
            except ValueError as error:
                raise ValueError(
                    f"AkShare {field_name} must contain an ISO date or datetime"
                ) from error

    @classmethod
    def _optional_provider_date(cls, value: object, field_name: str) -> date | None:
        if cls._is_missing(value):
            return None
        return cls._provider_date(value, field_name)

    @staticmethod
    def _period_type(value: date) -> FinancialPeriodType:
        try:
            return {
                (3, 31): FinancialPeriodType.Q1,
                (6, 30): FinancialPeriodType.HALF_YEAR,
                (9, 30): FinancialPeriodType.Q3,
                (12, 31): FinancialPeriodType.ANNUAL,
            }[(value.month, value.day)]
        except KeyError as error:
            raise ValueError("unsupported A-share financial report period") from error

    @staticmethod
    def _period_start(value: date, basis: FinancialValueBasis) -> date:
        basis = FinancialValueBasis(basis)
        if basis is FinancialValueBasis.POINT_IN_TIME:
            return value
        if basis is FinancialValueBasis.CUMULATIVE_YTD:
            return date(value.year, 1, 1)
        if basis is FinancialValueBasis.SINGLE_QUARTER:
            return {
                (3, 31): date(value.year, 1, 1),
                (6, 30): date(value.year, 4, 1),
                (9, 30): date(value.year, 7, 1),
                (12, 31): date(value.year, 10, 1),
            }[(value.month, value.day)]
        return date(value.year - 1, value.month, value.day) + timedelta(days=1)

    @classmethod
    def _is_missing(cls, value: object) -> bool:
        plain = cls._plain_scalar(value)
        if plain is None:
            return True
        if isinstance(plain, str):
            return plain.strip().lower() in _MISSING_TEXT
        if isinstance(plain, float):
            return not math.isfinite(plain)
        if isinstance(plain, Decimal):
            return not plain.is_finite()
        return False

    @classmethod
    def _numeric(cls, value: object, field_name: str) -> tuple[Decimal, str | None]:
        plain = cls._plain_scalar(value)
        if isinstance(plain, bool):
            raise TypeError(f"{field_name} must be numeric")
        warning = None
        source: object
        if isinstance(plain, float):
            if not math.isfinite(plain):
                raise ValueError(f"{field_name} must be finite")
            warning = (
                "provider numeric value arrived through binary float and was converted "
                "via repr; source precision may already be limited"
            )
            source = repr(plain)
        else:
            source = plain
        try:
            result = source if isinstance(source, Decimal) else Decimal(str(source))
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"{field_name} must be numeric") from error
        if not result.is_finite():
            raise ValueError(f"{field_name} must be finite")
        return result, warning

    @staticmethod
    def _plain_scalar(value: object) -> object:
        if value is None or isinstance(value, (str, int, float, bool, Decimal, date)):
            return value
        item = getattr(value, "item", None)
        if callable(item):
            return item()
        return value


class AkShareRateLimitedRequestExecutor:
    """Sequential provider boundary with explicit spacing and bounded retries."""

    def __init__(
        self,
        *,
        minimum_interval_seconds: float,
        max_attempts: int,
        retry_backoff_seconds: float,
        monotonic: Callable[[], float],
        sleep: Callable[[float], None],
        retryable_errors: tuple[type[Exception], ...],
    ) -> None:
        for value, name in (
            (minimum_interval_seconds, "minimum_interval_seconds"),
            (retry_backoff_seconds, "retry_backoff_seconds"),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")
        if not retryable_errors or any(
            not isinstance(error, type) or not issubclass(error, Exception)
            for error in retryable_errors
        ):
            raise ValueError("retryable_errors must contain Exception types")
        self._minimum_interval_seconds = float(minimum_interval_seconds)
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = float(retry_backoff_seconds)
        self._monotonic = monotonic
        self._sleep = sleep
        self._retryable_errors = retryable_errors
        self._last_started_at: float | None = None

    def execute(self, operation: str, action: Callable[[], object]) -> object:
        _text(operation, "operation")
        if not callable(action):
            raise TypeError("action must be callable")
        attempt = 0
        while True:
            self._wait_for_rate_limit()
            attempt += 1
            try:
                return action()
            except self._retryable_errors:
                if attempt >= self._max_attempts:
                    raise
                self._sleep(self._retry_backoff_seconds * attempt)

    def _wait_for_rate_limit(self) -> None:
        now = self._monotonic()
        if not math.isfinite(now):
            raise ValueError("monotonic clock must return a finite number")
        if self._last_started_at is not None:
            if now < self._last_started_at:
                raise ValueError("monotonic clock moved backwards")
            remaining = self._minimum_interval_seconds - (now - self._last_started_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._monotonic()
        self._last_started_at = now


class AkShareFinancialSource:
    provider_id = "akshare"

    def __init__(
        self,
        *,
        client: AkShareFinancialClient,
        normalizer: (
            AkShareFinancialNormalizer
            | Mapping[StatementType, AkShareFinancialNormalizer]
        ),
        request_executor: AkShareRequestExecutor,
        evidence_capture: FinancialEvidenceCapture,
        evidence_source_urls: Mapping[StatementType, str],
        clock: Callable[[], datetime],
        snapshot_cache: AkShareFinancialSnapshotCache | None = None,
    ) -> None:
        self._client = client
        if isinstance(normalizer, AkShareFinancialNormalizer):
            self._normalizers = {statement_type: normalizer for statement_type in StatementType}
        else:
            normalizers = {
                StatementType(statement_type): value
                for statement_type, value in normalizer.items()
            }
            if set(normalizers) != set(StatementType) or any(
                not isinstance(value, AkShareFinancialNormalizer)
                for value in normalizers.values()
            ):
                raise ValueError(
                    "statement-specific AkShare normalizers must cover all three statements"
                )
            self._normalizers = normalizers
        self._request_executor = request_executor
        self._evidence_capture = evidence_capture
        urls = {
            StatementType(key): _text(value, "evidence_source_url")
            for key, value in evidence_source_urls.items()
        }
        if set(urls) != set(StatementType):
            raise ValueError("evidence_source_urls must cover all three statements")
        self._evidence_source_urls = urls
        self._clock = clock
        self._snapshot_cache = (
            AkShareInMemoryFinancialSnapshotCache() if snapshot_cache is None else snapshot_cache
        )

    def fetch(
        self,
        work_unit: FinancialBackfillWorkUnit,
        *,
        allow_read_through_cache: bool,
    ) -> FinancialProviderBatch:
        if work_unit.provider_id != self.provider_id:
            raise ValueError("AkShare source provider does not match work unit")
        if type(allow_read_through_cache) is not bool:
            raise TypeError("allow_read_through_cache must be a boolean")
        expected_table, endpoint = _ENDPOINTS[work_unit.statement_type]
        if work_unit.provider_table != expected_table:
            raise ValueError("AkShare provider table does not match statement type")

        snapshots: list[AkShareFinancialSnapshot] = []
        for canonical_symbol in work_unit.symbols:
            provider_symbol = canonical_symbol.replace(".", "")
            key = AkShareFinancialSnapshotKey(
                provider_id=self.provider_id,
                endpoint=endpoint,
                canonical_symbol=canonical_symbol,
            )
            snapshot = self._cached_snapshot(key) if allow_read_through_cache else None
            if snapshot is None:
                operation = f"{endpoint.value}:{provider_symbol}"
                loaded = self._request_executor.execute(
                    operation,
                    partial(
                        self._load_snapshot,
                        key=key,
                        endpoint=endpoint,
                        provider_symbol=provider_symbol,
                        canonical_symbol=canonical_symbol,
                        allow_read_through_cache=allow_read_through_cache,
                    ),
                )
                snapshot = self._require_snapshot(loaded, key)
            snapshots.append(snapshot)
        provider_records = tuple(
            record for snapshot in snapshots for record in snapshot.materialize()
        )
        retrieved_at = max(snapshot.retrieved_at for snapshot in snapshots)
        evidence = self._evidence_capture.capture_provider_response(
            work_unit=work_unit,
            provider_id=self.provider_id,
            source_url=self._evidence_source_urls[work_unit.statement_type],
            provider_records=provider_records,
            retrieved_at=retrieved_at,
        )
        return self._normalizers[work_unit.statement_type].normalize(
            work_unit=work_unit,
            provider_records=provider_records,
            evidence=evidence,
            retrieved_at=retrieved_at,
        )

    def _load_snapshot(
        self,
        *,
        key: AkShareFinancialSnapshotKey,
        endpoint: AkShareEndpoint,
        provider_symbol: str,
        canonical_symbol: str,
        allow_read_through_cache: bool,
    ) -> AkShareFinancialSnapshot:
        if allow_read_through_cache:
            cached = self._cached_snapshot(key)
            if cached is not None:
                return cached
        frame = self._fetch_frame(endpoint, provider_symbol)
        records = self._frame_records(
            frame,
            requested_symbol=canonical_symbol,
        )
        snapshot = AkShareFinancialSnapshot.from_provider_records(
            key=key,
            provider_records=records,
            retrieved_at=self._clock(),
        )
        if allow_read_through_cache:
            self._snapshot_cache.put(snapshot)
        return snapshot

    def _cached_snapshot(
        self,
        key: AkShareFinancialSnapshotKey,
    ) -> AkShareFinancialSnapshot | None:
        value = self._snapshot_cache.get(key)
        if value is None:
            return None
        return self._require_snapshot(value, key)

    @staticmethod
    def _require_snapshot(
        value: object,
        key: AkShareFinancialSnapshotKey,
    ) -> AkShareFinancialSnapshot:
        if not isinstance(value, AkShareFinancialSnapshot) or value.key != key:
            raise ValueError("AkShare cache returned a snapshot for another source key")
        return value

    def _fetch_frame(self, endpoint: AkShareEndpoint, symbol: str) -> object:
        if endpoint is AkShareEndpoint.BALANCE_SHEET:
            return self._client.stock_balance_sheet_by_report_em(symbol=symbol)
        if endpoint is AkShareEndpoint.INCOME_STATEMENT:
            return self._client.stock_profit_sheet_by_report_em(symbol=symbol)
        return self._client.stock_cash_flow_sheet_by_report_em(symbol=symbol)

    @classmethod
    def _frame_records(
        cls,
        frame: object,
        *,
        requested_symbol: str,
    ) -> tuple[Mapping[str, object], ...]:
        to_dict = getattr(frame, "to_dict", None)
        if not callable(to_dict):
            raise TypeError("AkShare financial endpoint must return a DataFrame-like object")
        raw_records = to_dict(orient="records")
        if not isinstance(raw_records, list):
            raise TypeError("AkShare DataFrame records must be a list")
        records: list[Mapping[str, object]] = []
        for raw_record in raw_records:
            if not isinstance(raw_record, Mapping):
                raise TypeError("AkShare DataFrame record must be a mapping")
            if _REQUESTED_SYMBOL_FIELD in raw_record:
                raise ValueError("AkShare response used a reserved internal field")
            sanitized = {str(key): cls._evidence_scalar(value) for key, value in raw_record.items()}
            sanitized[_REQUESTED_SYMBOL_FIELD] = requested_symbol
            records.append(sanitized)
        return tuple(records)

    @classmethod
    def _evidence_scalar(cls, value: object) -> object:
        plain = AkShareFinancialNormalizer._plain_scalar(value)
        if plain is None or isinstance(plain, (str, int, float, bool, Decimal)):
            if isinstance(plain, float) and not math.isfinite(plain):
                return None
            if isinstance(plain, Decimal) and not plain.is_finite():
                return None
            return plain
        if isinstance(plain, datetime):
            return plain.isoformat()
        if isinstance(plain, date):
            return plain.isoformat()
        raise TypeError(f"unsupported AkShare DataFrame scalar type: {type(plain).__name__}")


__all__ = [
    "AkShareFieldContract",
    "AkShareFinancialClient",
    "AkShareFinancialNormalizer",
    "AkShareFinancialSnapshot",
    "AkShareFinancialSnapshotCache",
    "AkShareFinancialSnapshotKey",
    "AkShareFinancialSource",
    "AkShareInMemoryFinancialSnapshotCache",
    "AkShareRateLimitedRequestExecutor",
    "AkShareRequestExecutor",
]
