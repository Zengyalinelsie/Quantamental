"""Factor Service financial-table edge adapter with explicit evidence capture."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
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
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType
from a_share_platform.ports.financial_backfill import FinancialEvidenceCapture


class FactorServiceTableReader(Protocol):
    def iter_v2_table_rows(
        self,
        *,
        table_name: str,
        primary_key_name: str | None,
        primary_key_values: Sequence[str],
        columns: Sequence[str],
        filter_date: str,
        start_date: str,
        end_date: str,
        page_size: int,
        allow_date_only_query: bool,
        allow_read_through_cache: bool,
    ) -> Iterator[Mapping[str, object]]: ...


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


@dataclass(frozen=True)
class FactorServiceFieldContract:
    provider_field: str
    provider_unit: str
    scale_to_canonical: Decimal
    currency: str | None
    statement_scope: FinancialStatementScope
    value_basis: FinancialValueBasis

    def __post_init__(self) -> None:
        _text(self.provider_field, "provider_field")
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


class FactorServiceFinancialNormalizer:
    def __init__(self, fields: tuple[FactorServiceFieldContract, ...]) -> None:
        self._fields = tuple(fields)
        if not self._fields:
            raise ValueError("Factor Service normalizer requires at least one field contract")
        names = tuple(field.provider_field for field in self._fields)
        if len(names) != len(set(names)):
            raise ValueError("Factor Service field contracts must be unique")

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
        symbol_by_code: dict[str, str] = {}
        for symbol in work_unit.symbols:
            code = symbol.split(".", 1)[1]
            if code in symbol_by_code:
                raise ValueError("Factor Service code is ambiguous across work-unit markets")
            symbol_by_code[code] = symbol

        seen_records: set[tuple[str, date]] = set()
        rows: list[ProviderFinancialRow] = []
        accepted_symbols: set[str] = set()
        missing_values = 0
        period_type = self._period_type(work_unit.report_period_end)
        for provider_record in provider_records:
            source_code = self._source_code(provider_record.get("scode"))
            canonical_symbol = symbol_by_code.get(source_code)
            if canonical_symbol is None:
                raise ValueError("Factor Service response symbol is outside the work unit")
            response_period = self._response_date(provider_record.get("report_period_end"))
            if response_period != work_unit.report_period_end:
                raise ValueError("Factor Service response period is outside the work unit")
            record_key = (source_code, response_period)
            if record_key in seen_records:
                raise ValueError("duplicate Factor Service provider record")
            seen_records.add(record_key)
            record_digest = hashlib.sha256(
                (
                    f"{work_unit.provider_id}|{work_unit.provider_table}|{source_code}|"
                    f"{response_period.isoformat()}|{evidence.content_hash}"
                ).encode()
            ).hexdigest()[:24]
            provider_record_id = f"factor-service-row:{record_digest}"
            record_had_value = False
            for field in self._fields:
                raw_value = provider_record.get(field.provider_field)
                if raw_value is None or raw_value == "":
                    missing_values += 1
                    continue
                numeric = self._decimal(raw_value, field.provider_field)
                field_digest = hashlib.sha256(
                    f"{provider_record_id}|{field.provider_field}".encode()
                ).hexdigest()[:24]
                warnings = ["provider revision semantics unavailable"]
                if field.statement_scope is FinancialStatementScope.UNKNOWN:
                    warnings.append("financial statement scope unavailable")
                rows.append(
                    ProviderFinancialRow(
                        row_id=f"provider-financial-row:{field_digest}",
                        provider_id=work_unit.provider_id,
                        provider_table=work_unit.provider_table,
                        provider_record_id=provider_record_id,
                        provider_field=field.provider_field,
                        market="XSHG" if canonical_symbol.startswith("SH.") else "XSHE",
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
                accepted_symbols.add(canonical_symbol)

        warnings = [
            "Factor Service rows are normalized_current and not strict-historical evidence",
            "provider announcement and revision timestamps are unavailable",
        ]
        if missing_values:
            warnings.append(f"missing_provider_value_count={missing_values}")
        return FinancialProviderBatch(
            work_unit=work_unit,
            evidence=evidence,
            rows=tuple(rows),
            provider_record_count=len(provider_records),
            missing_value_count=missing_values,
            accepted_symbols=tuple(sorted(accepted_symbols)),
            trust_state=DataTrustState.NORMALIZED_CURRENT,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _source_code(value: object) -> str:
        if not isinstance(value, str) or len(value) != 6 or not value.isdigit():
            raise ValueError("Factor Service scode must contain six digits")
        return value

    @staticmethod
    def _response_date(value: object) -> date:
        if not isinstance(value, str):
            raise TypeError("Factor Service report_period_end must be an ISO date")
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("Factor Service report_period_end must be an ISO date") from error

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
            raise ValueError("unsupported A-share financial report period end") from error

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
        previous_year_end = date(value.year - 1, value.month, value.day)
        return previous_year_end + timedelta(days=1)

    @staticmethod
    def _decimal(value: object, field_name: str) -> Decimal:
        if isinstance(value, float):
            raise TypeError(f"{field_name} must not pass through float")
        if isinstance(value, bool):
            raise TypeError(f"{field_name} must be numeric")
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, ValueError) as error:
            raise ValueError(f"{field_name} must be numeric") from error
        if not result.is_finite():
            raise ValueError(f"{field_name} must be finite")
        return result


class FactorServiceFinancialSource:
    provider_id = "factor_service_ths"

    def __init__(
        self,
        *,
        client: FactorServiceTableReader,
        normalizer: FactorServiceFinancialNormalizer,
        evidence_capture: FinancialEvidenceCapture,
        evidence_source_url: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._client = client
        self._normalizer = normalizer
        self._evidence_capture = evidence_capture
        self._evidence_source_url = _text(evidence_source_url, "evidence_source_url")
        self._clock = clock

    def fetch(
        self,
        work_unit: FinancialBackfillWorkUnit,
        *,
        allow_read_through_cache: bool,
    ) -> FinancialProviderBatch:
        if work_unit.provider_id != self.provider_id:
            raise ValueError("Factor Service source provider does not match work unit")
        if not allow_read_through_cache:
            raise PermissionError("Factor Service read-through cache acknowledgement is required")
        report_period = work_unit.report_period_end.isoformat()
        provider_records = tuple(
            self._client.iter_v2_table_rows(
                table_name=work_unit.provider_table,
                primary_key_name="scode",
                primary_key_values=tuple(symbol.split(".", 1)[1] for symbol in work_unit.symbols),
                columns=("scode", "report_period_end", *self._normalizer.provider_fields),
                filter_date="report_period_end",
                start_date=report_period,
                end_date=report_period,
                page_size=min(5000, len(work_unit.symbols)),
                allow_date_only_query=False,
                allow_read_through_cache=allow_read_through_cache,
            )
        )
        retrieved_at = self._clock()
        evidence = self._evidence_capture.capture_provider_response(
            work_unit=work_unit,
            provider_id=self.provider_id,
            source_url=self._evidence_source_url,
            provider_records=provider_records,
            retrieved_at=retrieved_at,
        )
        return self._normalizer.normalize(
            work_unit=work_unit,
            provider_records=provider_records,
            evidence=evidence,
            retrieved_at=retrieved_at,
        )


__all__ = [
    "FactorServiceFieldContract",
    "FactorServiceFinancialNormalizer",
    "FactorServiceFinancialSource",
]
