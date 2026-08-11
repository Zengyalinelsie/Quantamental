"""Canonical financial metric, provider mapping, and quality-rule contracts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _decimal(value: Decimal | str | int, field_name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field_name} must be numeric") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


class StatementType(str, Enum):
    BALANCE_SHEET = "balance_sheet"
    INCOME_STATEMENT = "income_statement"
    CASH_FLOW_STATEMENT = "cash_flow_statement"


class MetricUnit(str, Enum):
    CURRENCY = "currency"
    CURRENCY_PER_SHARE = "currency_per_share"
    SHARES = "shares"
    RATIO = "ratio"
    COUNT = "count"
    DAYS = "days"
    TEXT = "text"


class CurrencyRequirement(str, Enum):
    REQUIRED = "required"
    FORBIDDEN = "forbidden"


class SignConvention(str, Enum):
    NATURAL = "natural"
    INFLOW_POSITIVE = "inflow_positive"
    OUTFLOW_POSITIVE = "outflow_positive"
    EXPENSE_NEGATIVE = "expense_negative"


class MappingMethod(str, Enum):
    EXACT = "exact"
    FORMULA = "formula"
    MANUAL_VERIFIED = "manual_verified"
    FUZZY = "fuzzy"


class MappingUseScope(str, Enum):
    """The approved downstream use of one immutable provider-field mapping."""

    CURRENT_RESEARCH = "current_research"
    STRICT_HISTORICAL = "strict_historical"
    PRODUCTION = "production"


class QualityRuleKind(str, Enum):
    ACCOUNTING_IDENTITY = "accounting_identity"
    CROSS_STATEMENT = "cross_statement"
    RANGE = "range"


class QualitySeverity(str, Enum):
    WARNING = "warning"
    BLOCK = "block"


class QualityStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class UnmappedFieldStatus(str, Enum):
    PENDING = "pending"
    MAPPED = "mapped"
    IGNORED = "ignored"


@dataclass(frozen=True)
class CanonicalMetric:
    metric_code: str
    canonical_name: str
    statement_type: StatementType
    unit: MetricUnit
    currency_requirement: CurrencyRequirement
    sign_convention: SignConvention
    description: str

    def __post_init__(self) -> None:
        for name in ("metric_code", "canonical_name", "description"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        unit = MetricUnit(self.unit)
        currency = CurrencyRequirement(self.currency_requirement)
        object.__setattr__(self, "unit", unit)
        object.__setattr__(self, "currency_requirement", currency)
        object.__setattr__(self, "sign_convention", SignConvention(self.sign_convention))
        currency_units = {MetricUnit.CURRENCY, MetricUnit.CURRENCY_PER_SHARE}
        if unit in currency_units and currency is not CurrencyRequirement.REQUIRED:
            raise ValueError("currency unit requires currency")
        if unit not in currency_units and currency is not CurrencyRequirement.FORBIDDEN:
            raise ValueError("non-currency unit must forbid currency")


@dataclass(frozen=True)
class MappingVersion:
    mapping_version_id: str
    provider_id: str
    created_at: datetime
    content_hash: str
    code_version: str

    def __post_init__(self) -> None:
        for name in ("mapping_version_id", "provider_id", "code_version"):
            _text(getattr(self, name), name)
        _aware(self.created_at, "created_at")
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")


@dataclass(frozen=True)
class ProviderFieldMapping:
    mapping_id: str
    mapping_version_id: str
    provider_id: str
    statement_type: StatementType
    source_field: str
    metric_code: str
    method: MappingMethod
    formula: str | None
    allowed_use_scopes: frozenset[MappingUseScope]

    def __post_init__(self) -> None:
        for name in (
            "mapping_id",
            "mapping_version_id",
            "provider_id",
            "source_field",
            "metric_code",
        ):
            _text(getattr(self, name), name)
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        method = MappingMethod(self.method)
        object.__setattr__(self, "method", method)
        scopes = frozenset(MappingUseScope(scope) for scope in self.allowed_use_scopes)
        if not scopes:
            raise ValueError("allowed_use_scopes must not be empty")
        object.__setattr__(self, "allowed_use_scopes", scopes)
        if method is MappingMethod.FORMULA:
            _text(self.formula or "", "formula")
        elif self.formula is not None:
            raise ValueError("formula is only valid for formula mapping")
        if method is MappingMethod.FUZZY and MappingUseScope.PRODUCTION in scopes:
            raise ValueError("fuzzy mapping cannot be allowed for production")
        if self.provider_id in {"akshare", "provider:akshare"} and scopes != {
            MappingUseScope.CURRENT_RESEARCH
        }:
            raise ValueError("AkShare mapping is allowed only for current_research")

    def allows(self, use_scope: MappingUseScope) -> bool:
        return MappingUseScope(use_scope) in self.allowed_use_scopes


@dataclass(frozen=True)
class QualityTerm:
    metric_code: str
    coefficient: Decimal

    def __post_init__(self) -> None:
        _text(self.metric_code, "metric_code")
        coefficient = _decimal(self.coefficient, "coefficient")
        if coefficient == 0:
            raise ValueError("coefficient cannot be zero")
        object.__setattr__(self, "coefficient", coefficient)


@dataclass(frozen=True)
class FinancialQualityResult:
    rule_id: str
    status: QualityStatus
    severity: QualitySeverity
    residual: Decimal | None
    missing_metric_codes: tuple[str, ...]

    @property
    def blocks_downstream(self) -> bool:
        return (
            self.status in {QualityStatus.FAILED, QualityStatus.UNAVAILABLE}
            and self.severity is QualitySeverity.BLOCK
        )


@dataclass(frozen=True)
class FinancialQualityRule:
    rule_id: str
    name: str
    rule_kind: QualityRuleKind
    terms: tuple[QualityTerm, ...]
    tolerance: Decimal
    severity: QualitySeverity

    def __post_init__(self) -> None:
        _text(self.rule_id, "rule_id")
        _text(self.name, "name")
        object.__setattr__(self, "rule_kind", QualityRuleKind(self.rule_kind))
        terms = tuple(self.terms)
        if len(terms) < 2:
            raise ValueError("quality rule requires at least two terms")
        codes = tuple(term.metric_code for term in terms)
        if len(codes) != len(set(codes)):
            raise ValueError("quality rule metric codes must be unique")
        object.__setattr__(self, "terms", terms)
        tolerance = _decimal(self.tolerance, "tolerance")
        if tolerance < 0:
            raise ValueError("tolerance cannot be negative")
        object.__setattr__(self, "tolerance", tolerance)
        object.__setattr__(self, "severity", QualitySeverity(self.severity))

    def evaluate(
        self,
        values: Mapping[str, Decimal | int | str | None],
    ) -> FinancialQualityResult:
        missing = tuple(
            term.metric_code
            for term in self.terms
            if term.metric_code not in values or values[term.metric_code] is None
        )
        if missing:
            return FinancialQualityResult(
                rule_id=self.rule_id,
                status=QualityStatus.UNAVAILABLE,
                severity=self.severity,
                residual=None,
                missing_metric_codes=missing,
            )
        residual = sum(
            (
                term.coefficient
                * _decimal(values[term.metric_code], f"value[{term.metric_code}]")  # type: ignore[arg-type]
                for term in self.terms
            ),
            Decimal(0),
        )
        return FinancialQualityResult(
            rule_id=self.rule_id,
            status=(
                QualityStatus.PASSED
                if abs(residual) <= self.tolerance
                else QualityStatus.FAILED
            ),
            severity=self.severity,
            residual=residual,
            missing_metric_codes=(),
        )


@dataclass(frozen=True)
class UnmappedProviderField:
    unmapped_field_id: str
    provider_id: str
    statement_type: StatementType
    source_field: str
    mapping_version_id: str
    discovered_at: datetime
    raw_object_id: str
    status: UnmappedFieldStatus = UnmappedFieldStatus.PENDING
    resolved_mapping_id: str | None = None
    resolution_reason: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "unmapped_field_id",
            "provider_id",
            "source_field",
            "mapping_version_id",
            "raw_object_id",
        ):
            _text(getattr(self, name), name)
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        _aware(self.discovered_at, "discovered_at")
        status = UnmappedFieldStatus(self.status)
        object.__setattr__(self, "status", status)
        if status is UnmappedFieldStatus.PENDING:
            if self.resolved_mapping_id is not None or self.resolution_reason is not None:
                raise ValueError("pending unmapped field cannot have a resolution")
        elif status is UnmappedFieldStatus.MAPPED:
            _text(self.resolved_mapping_id or "", "resolved_mapping_id")
        elif status is UnmappedFieldStatus.IGNORED:
            _text(self.resolution_reason or "", "resolution_reason")
