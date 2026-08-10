import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.domain.financial_sources import (
    AvailabilityMethod,
    FinancialSourceAccessMode,
    FinancialSourcePermissionError,
    FinancialSourceProfile,
    FinancialSourceQualification,
    FinancialSourceRole,
    FinancialSourceRouter,
    FinancialSourceUnavailable,
    FinancialStatementScope,
    FinancialValueBasis,
    ProviderFinancialRow,
    ReportVersionType,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType
from a_share_platform.domain.run_context import DataMode

RETRIEVED_AT = datetime(2026, 8, 10, 18, tzinfo=UTC)
AVAILABLE_AT = datetime(2024, 4, 30, 0, 13, tzinfo=UTC)
ANNOUNCED_AT = datetime(2024, 4, 30, 0, 12, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def profile(
    *,
    provider_id: str = "wind",
    role: FinancialSourceRole = FinancialSourceRole.PRIMARY,
    access_mode: FinancialSourceAccessMode = FinancialSourceAccessMode.READ_ONLY,
    qualification: FinancialSourceQualification = (
        FinancialSourceQualification.NORMALIZED_CURRENT_APPROVED
    ),
    trust_ceiling: DataTrustState = DataTrustState.NORMALIZED_CURRENT,
    retention_allowed: bool = True,
    bulk_persistence_allowed: bool = True,
    supplies_revision_history: bool = False,
    supplies_exact_available_at: bool = False,
) -> FinancialSourceProfile:
    return FinancialSourceProfile(
        profile_version=f"financial-source:{provider_id}:v1",
        provider_id=provider_id,
        role=role,
        markets=frozenset({"XSHG", "XSHE"}),
        statements=frozenset(StatementType),
        access_mode=access_mode,
        qualification=qualification,
        trust_ceiling=trust_ceiling,
        retention_allowed=retention_allowed,
        bulk_persistence_allowed=bulk_persistence_allowed,
        supplies_revision_history=supplies_revision_history,
        supplies_exact_available_at=supplies_exact_available_at,
        max_rows_per_request=5000,
        warnings=(),
    )


def provider_row(**overrides: object) -> ProviderFinancialRow:
    values: dict[str, object] = {
        "row_id": "provider-row:ths:600000:2023:revenue",
        "provider_id": "factor_service_ths",
        "provider_table": "income_statement",
        "provider_record_id": "ths:600000:2023-12-31",
        "provider_field": "ths_operating_revenue_stock",
        "market": "XSHG",
        "source_symbol": "600000",
        "statement_type": StatementType.INCOME_STATEMENT,
        "statement_scope": FinancialStatementScope.CONSOLIDATED,
        "report_period_start": date(2023, 1, 1),
        "report_period_end": date(2023, 12, 31),
        "period_type": FinancialPeriodType.ANNUAL,
        "value_basis": FinancialValueBasis.CUMULATIVE_YTD,
        "raw_value": Decimal("536409.19"),
        "provider_unit": "CNY_10K",
        "scale_to_canonical": Decimal(10000),
        "currency": "CNY",
        "report_version_type": ReportVersionType.ORIGINAL,
        "revision_sequence": 0,
        "announced_at": ANNOUNCED_AT,
        "available_at": AVAILABLE_AT,
        "availability_method": AvailabilityMethod.PROVIDER_EXACT,
        "provider_updated_at": AVAILABLE_AT,
        "retrieved_at": RETRIEVED_AT,
        "raw_object_id": "raw:factor-service:600000:2023",
        "raw_object_hash": HASH,
        "source_url": "https://provider.invalid/records/600000/2023",
        "warnings": (),
    }
    values.update(overrides)
    return ProviderFinancialRow(**values)  # type: ignore[arg-type]


class ProviderFinancialRowTest(unittest.TestCase):
    def test_money_scaling_is_decimal_and_preserves_statement_semantics(self) -> None:
        row = provider_row()
        self.assertEqual(row.scaled_numeric_value, Decimal("5364091900.00"))
        self.assertEqual(row.statement_scope, FinancialStatementScope.CONSOLIDATED)
        self.assertEqual(row.value_basis, FinancialValueBasis.CUMULATIVE_YTD)
        with self.assertRaisesRegex(TypeError, "float"):
            provider_row(raw_value=536409.19)
        with self.assertRaises(FrozenInstanceError):
            row.provider_id = "other"  # type: ignore[misc]

    def test_availability_method_is_explicit_and_cannot_invent_pit_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact availability"):
            provider_row(
                available_at=None,
                availability_method=AvailabilityMethod.PROVIDER_EXACT,
            )
        with self.assertRaisesRegex(ValueError, "unavailable"):
            provider_row(availability_method=AvailabilityMethod.UNAVAILABLE)
        conservative = provider_row(
            announced_at=None,
            available_at=RETRIEVED_AT,
            availability_method=AvailabilityMethod.CONSERVATIVE_RETRIEVAL_TIME,
        )
        self.assertFalse(conservative.is_strict_time_eligible)
        with self.assertRaisesRegex(ValueError, "retrieved_at"):
            replace(
                conservative,
                available_at=AVAILABLE_AT,
            )

    def test_corrected_report_requires_a_positive_explicit_revision(self) -> None:
        with self.assertRaisesRegex(ValueError, "revision_sequence"):
            provider_row(
                report_version_type=ReportVersionType.CORRECTED,
                revision_sequence=0,
            )
        corrected = provider_row(
            report_version_type=ReportVersionType.CORRECTED,
            revision_sequence=1,
        )
        self.assertEqual(corrected.revision_sequence, 1)


class FinancialSourceProfileTest(unittest.TestCase):
    def test_pit_approval_requires_exact_availability_revision_history_and_trust(self) -> None:
        with self.assertRaisesRegex(ValueError, "PIT approval"):
            profile(
                qualification=FinancialSourceQualification.PIT_APPROVED,
                trust_ceiling=DataTrustState.PIT_VERIFIED,
            )
        official = profile(
            provider_id="official_disclosure",
            role=FinancialSourceRole.AUTHORITY,
            qualification=FinancialSourceQualification.PIT_APPROVED,
            trust_ceiling=DataTrustState.PIT_VERIFIED,
            supplies_revision_history=True,
            supplies_exact_available_at=True,
        )
        official.require_access(
            data_mode=DataMode.STRICT_HISTORICAL,
            bulk_persistence=True,
            allow_read_through_cache=False,
        )

    def test_bulk_and_read_through_cache_require_explicit_permission(self) -> None:
        current = profile(
            provider_id="factor_service_ths",
            role=FinancialSourceRole.FALLBACK,
            access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
        )
        with self.assertRaisesRegex(FinancialSourcePermissionError, "read-through"):
            current.require_access(
                data_mode=DataMode.CURRENT_RESEARCH,
                bulk_persistence=True,
                allow_read_through_cache=False,
            )
        current.require_access(
            data_mode=DataMode.CURRENT_RESEARCH,
            bulk_persistence=True,
            allow_read_through_cache=True,
        )
        with self.assertRaisesRegex(ValueError, "retention"):
            profile(retention_allowed=False, bulk_persistence_allowed=True)

    def test_candidate_profile_cannot_be_used_as_if_qualified(self) -> None:
        candidate = profile(
            qualification=FinancialSourceQualification.CANDIDATE,
            bulk_persistence_allowed=False,
        )
        with self.assertRaisesRegex(FinancialSourcePermissionError, "candidate"):
            candidate.require_access(
                data_mode=DataMode.CURRENT_RESEARCH,
                bulk_persistence=False,
                allow_read_through_cache=False,
            )


class FinancialSourceRouterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.factor_service = profile(
            provider_id="factor_service_ths",
            role=FinancialSourceRole.PRIMARY,
            access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
            qualification=FinancialSourceQualification.CANDIDATE,
            bulk_persistence_allowed=False,
        )
        self.wind = profile(
            role=FinancialSourceRole.FALLBACK,
            qualification=FinancialSourceQualification.CANDIDATE,
            bulk_persistence_allowed=False,
        )
        self.official = profile(
            provider_id="official_disclosure",
            role=FinancialSourceRole.AUTHORITY,
            qualification=FinancialSourceQualification.PIT_APPROVED,
            trust_ceiling=DataTrustState.PIT_VERIFIED,
            supplies_revision_history=True,
            supplies_exact_available_at=True,
        )
        self.router = FinancialSourceRouter(
            (self.factor_service, self.official, self.wind)
        )

    def test_unqualified_factor_service_and_wind_cannot_be_selected(self) -> None:
        candidates_only = FinancialSourceRouter((self.factor_service, self.wind))
        with self.assertRaisesRegex(FinancialSourceUnavailable, "current_research"):
            candidates_only.primary(
                market="XSHG",
                statement_type=StatementType.BALANCE_SHEET,
                data_mode=DataMode.CURRENT_RESEARCH,
                bulk_persistence=False,
                allow_read_through_cache=True,
            )

    def test_hypothetically_qualified_route_keeps_fallback_explicit(self) -> None:
        qualified_factor_service = profile(
            provider_id="factor_service_ths",
            role=FinancialSourceRole.PRIMARY,
            access_mode=FinancialSourceAccessMode.READ_THROUGH_CACHE,
        )
        qualified_wind = profile(role=FinancialSourceRole.FALLBACK)
        qualified_router = FinancialSourceRouter(
            (qualified_factor_service, self.official, qualified_wind)
        )
        selected = qualified_router.primary(
            market="XSHG",
            statement_type=StatementType.BALANCE_SHEET,
            data_mode=DataMode.CURRENT_RESEARCH,
            bulk_persistence=True,
            allow_read_through_cache=True,
        )
        self.assertEqual(selected.provider_id, "factor_service_ths")
        with self.assertRaisesRegex(ValueError, "reason"):
            qualified_router.fallback_after(
                failed_provider_id="factor_service_ths",
                reason="",
                market="XSHG",
                statement_type=StatementType.BALANCE_SHEET,
                data_mode=DataMode.CURRENT_RESEARCH,
                bulk_persistence=True,
                allow_read_through_cache=False,
            )
        fallback = qualified_router.fallback_after(
            failed_provider_id="factor_service_ths",
            reason="provider returned an empty response",
            market="XSHG",
            statement_type=StatementType.BALANCE_SHEET,
            data_mode=DataMode.CURRENT_RESEARCH,
            bulk_persistence=True,
            allow_read_through_cache=False,
        )
        self.assertEqual(fallback.provider_id, "wind")

    def test_strict_route_rejects_current_sources_and_selects_pit_authority(self) -> None:
        selected = self.router.primary(
            market="XSHE",
            statement_type=StatementType.CASH_FLOW_STATEMENT,
            data_mode=DataMode.STRICT_HISTORICAL,
            bulk_persistence=True,
            allow_read_through_cache=False,
        )
        self.assertEqual(selected.provider_id, "official_disclosure")
        without_official = FinancialSourceRouter((self.wind, self.factor_service))
        with self.assertRaisesRegex(FinancialSourceUnavailable, "strict_historical"):
            without_official.primary(
                market="XSHE",
                statement_type=StatementType.CASH_FLOW_STATEMENT,
                data_mode=DataMode.STRICT_HISTORICAL,
                bulk_persistence=True,
                allow_read_through_cache=True,
            )


if __name__ == "__main__":
    unittest.main()
