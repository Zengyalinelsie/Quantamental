"""Reviewed V1 field contracts for AkShare/Eastmoney current financial rows."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from a_share_platform.adapters.providers.akshare_financial import (
    AkShareFieldContract,
    AkShareFinancialNormalizer,
)
from a_share_platform.domain.financial_sources import (
    FinancialStatementScope,
    FinancialValueBasis,
)
from a_share_platform.domain.metrics import SignConvention, StatementType

AKSHARE_FINANCIAL_FIELD_PROFILE_VERSION = "akshare-eastmoney-financial-fields:v1"


@dataclass(frozen=True)
class AkShareFinancialFieldBinding:
    provider_field: str
    metric_code: str
    canonical_name: str
    description: str
    statement_type: StatementType
    provider_table: str
    value_basis: FinancialValueBasis
    sign_convention: SignConvention = SignConvention.NATURAL

    def __post_init__(self) -> None:
        for field_name in (
            "provider_field",
            "metric_code",
            "canonical_name",
            "description",
            "provider_table",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must not be empty")
        object.__setattr__(self, "statement_type", StatementType(self.statement_type))
        object.__setattr__(self, "value_basis", FinancialValueBasis(self.value_basis))
        object.__setattr__(self, "sign_convention", SignConvention(self.sign_convention))


AKSHARE_FINANCIAL_FIELD_BINDINGS_V1 = (
    AkShareFinancialFieldBinding(
        provider_field="TOTAL_ASSETS",
        metric_code="balance.total_assets",
        canonical_name="Total assets",
        description="Consolidation scope is unknown until provider metadata is verified.",
        statement_type=StatementType.BALANCE_SHEET,
        provider_table="balance_sheet",
        value_basis=FinancialValueBasis.POINT_IN_TIME,
    ),
    AkShareFinancialFieldBinding(
        provider_field="TOTAL_LIABILITIES",
        metric_code="balance.total_liabilities",
        canonical_name="Total liabilities",
        description="Consolidation scope is unknown until provider metadata is verified.",
        statement_type=StatementType.BALANCE_SHEET,
        provider_table="balance_sheet",
        value_basis=FinancialValueBasis.POINT_IN_TIME,
    ),
    AkShareFinancialFieldBinding(
        provider_field="TOTAL_EQUITY",
        metric_code="balance.total_equity",
        canonical_name="Total equity",
        description="Provider total equity; parent attribution is not inferred.",
        statement_type=StatementType.BALANCE_SHEET,
        provider_table="balance_sheet",
        value_basis=FinancialValueBasis.POINT_IN_TIME,
    ),
    AkShareFinancialFieldBinding(
        provider_field="TOTAL_OPERATE_INCOME",
        metric_code="income.total_operating_revenue",
        canonical_name="Total operating revenue",
        description=(
            "AkShare TOTAL_OPERATE_INCOME definition; not aliased to BaoStock MBRevenue."
        ),
        statement_type=StatementType.INCOME_STATEMENT,
        provider_table="income_statement",
        value_basis=FinancialValueBasis.CUMULATIVE_YTD,
    ),
    AkShareFinancialFieldBinding(
        provider_field="OPERATE_PROFIT",
        metric_code="income.operating_profit",
        canonical_name="Operating profit",
        description="Cumulative year-to-date operating profit reported by the provider.",
        statement_type=StatementType.INCOME_STATEMENT,
        provider_table="income_statement",
        value_basis=FinancialValueBasis.CUMULATIVE_YTD,
    ),
    AkShareFinancialFieldBinding(
        provider_field="NETPROFIT",
        metric_code="income.net_profit",
        canonical_name="Net profit",
        description="Provider net profit; parent attribution is not inferred.",
        statement_type=StatementType.INCOME_STATEMENT,
        provider_table="income_statement",
        value_basis=FinancialValueBasis.CUMULATIVE_YTD,
    ),
    AkShareFinancialFieldBinding(
        provider_field="NETCASH_OPERATE",
        metric_code="cash_flow.net_operating_cash_flow",
        canonical_name="Net cash flow from operating activities",
        description="Cumulative year-to-date net operating cash flow.",
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        provider_table="cash_flow",
        value_basis=FinancialValueBasis.CUMULATIVE_YTD,
        sign_convention=SignConvention.INFLOW_POSITIVE,
    ),
    AkShareFinancialFieldBinding(
        provider_field="NETCASH_INVEST",
        metric_code="cash_flow.net_investing_cash_flow",
        canonical_name="Net cash flow from investing activities",
        description="Cumulative year-to-date net investing cash flow.",
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        provider_table="cash_flow",
        value_basis=FinancialValueBasis.CUMULATIVE_YTD,
        sign_convention=SignConvention.INFLOW_POSITIVE,
    ),
    AkShareFinancialFieldBinding(
        provider_field="NETCASH_FINANCE",
        metric_code="cash_flow.net_financing_cash_flow",
        canonical_name="Net cash flow from financing activities",
        description="Cumulative year-to-date net financing cash flow.",
        statement_type=StatementType.CASH_FLOW_STATEMENT,
        provider_table="cash_flow",
        value_basis=FinancialValueBasis.CUMULATIVE_YTD,
        sign_convention=SignConvention.INFLOW_POSITIVE,
    ),
)


def akshare_financial_normalizers_v1() -> dict[StatementType, AkShareFinancialNormalizer]:
    result: dict[StatementType, AkShareFinancialNormalizer] = {}
    for statement_type in StatementType:
        bindings = tuple(
            binding
            for binding in AKSHARE_FINANCIAL_FIELD_BINDINGS_V1
            if binding.statement_type is statement_type
        )
        result[statement_type] = AkShareFinancialNormalizer(
            tuple(
                AkShareFieldContract(
                    provider_field=binding.provider_field,
                    provider_unit="CNY",
                    scale_to_canonical=Decimal(1),
                    currency="CNY",
                    statement_scope=FinancialStatementScope.UNKNOWN,
                    value_basis=binding.value_basis,
                )
                for binding in bindings
            )
        )
    return result


__all__ = [
    "AKSHARE_FINANCIAL_FIELD_BINDINGS_V1",
    "AKSHARE_FINANCIAL_FIELD_PROFILE_VERSION",
    "AkShareFinancialFieldBinding",
    "akshare_financial_normalizers_v1",
]
