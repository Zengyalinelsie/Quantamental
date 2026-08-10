import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.adapters.providers.factor_service_financial import (
    FactorServiceFieldContract,
    FactorServiceFinancialNormalizer,
    FactorServiceFinancialSource,
)
from a_share_platform.domain.disclosure import (
    RawObject,
    RawObjectKind,
    RetentionPolicy,
)
from a_share_platform.domain.financial_backfill import FinancialBackfillWorkUnit
from a_share_platform.domain.financial_sources import (
    FinancialStatementScope,
    FinancialValueBasis,
    ReportVersionType,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType

NOW = datetime(2026, 8, 10, 18, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def unit(
    statement_type: StatementType = StatementType.BALANCE_SHEET,
    provider_table: str = "balance_sheet",
) -> FinancialBackfillWorkUnit:
    return FinancialBackfillWorkUnit(
        plan_id="financial-backfill:csi300:v1",
        checkpoint_key=f"financial:{provider_table}:2024-12-31:bucket-0001",
        provider_id="factor_service_ths",
        provider_profile_version="financial-source:factor-service-ths:v1",
        benchmark_id="index:000300",
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="mapping:factor-service-ths:v1",
        statement_type=statement_type,
        provider_table=provider_table,
        report_period_end=date(2024, 12, 31),
        symbol_bucket_id="bucket-0001",
        symbols=("SH.600000",),
    )


def raw_object() -> RawObject:
    return RawObject(
        raw_object_id="raw:factor-service:balance-sheet:batch-1",
        object_kind=RawObjectKind.RESPONSE,
        content_hash=HASH,
        source_url="https://factor.example.internal/api/v2/table/query",
        provider_id="factor_service_ths",
        retrieved_at=NOW,
        media_type="application/json",
        storage_uri="memory://factor-service/batch-1",
        license_id="license:private-local-research-test",
        retention_policy=RetentionPolicy.INDEFINITE,
        retention_until=None,
        redistribution_allowed=False,
    )


def contract(
    provider_field: str,
    *,
    value_basis: FinancialValueBasis,
    provider_unit: str = "CNY_10K",
    scale: Decimal = Decimal(10000),
) -> FactorServiceFieldContract:
    return FactorServiceFieldContract(
        provider_field=provider_field,
        provider_unit=provider_unit,
        scale_to_canonical=scale,
        currency="CNY",
        statement_scope=FinancialStatementScope.UNKNOWN,
        value_basis=value_basis,
    )


class FactorServiceFinancialNormalizerTest(unittest.TestCase):
    def test_three_statement_contracts_preserve_decimal_units_period_and_unknown_scope(self) -> None:
        cases = (
            (
                StatementType.BALANCE_SHEET,
                "balance_sheet",
                "ths_total_assets_stock",
                FinancialValueBasis.POINT_IN_TIME,
                date(2024, 12, 31),
            ),
            (
                StatementType.INCOME_STATEMENT,
                "income_statement",
                "ths_operating_revenue_stock",
                FinancialValueBasis.CUMULATIVE_YTD,
                date(2024, 1, 1),
            ),
            (
                StatementType.CASH_FLOW_STATEMENT,
                "cash_flow",
                "ths_net_cash_flow_stock",
                FinancialValueBasis.CUMULATIVE_YTD,
                date(2024, 1, 1),
            ),
        )
        for statement_type, table, field, basis, expected_start in cases:
            with self.subTest(statement_type=statement_type):
                normalizer = FactorServiceFinancialNormalizer((contract(field, value_basis=basis),))
                batch = normalizer.normalize(
                    work_unit=unit(statement_type, table),
                    provider_records=(
                        {
                            "scode": "600000",
                            "report_period_end": "2024-12-31",
                            field: Decimal("123.45"),
                        },
                    ),
                    evidence=raw_object(),
                    retrieved_at=NOW,
                )
                row = batch.rows[0]
                self.assertEqual(row.raw_value, Decimal("123.45"))
                self.assertEqual(row.scaled_numeric_value, Decimal("1234500.00"))
                self.assertEqual(row.statement_type, statement_type)
                self.assertEqual(row.period_type, FinancialPeriodType.ANNUAL)
                self.assertEqual(row.value_basis, basis)
                self.assertEqual(row.report_period_start, expected_start)
                self.assertEqual(row.statement_scope, FinancialStatementScope.UNKNOWN)
                self.assertEqual(row.report_version_type, ReportVersionType.UNKNOWN)
                self.assertEqual(row.available_at, NOW)
                self.assertEqual(batch.trust_state, DataTrustState.NORMALIZED_CURRENT)

    def test_missing_value_is_counted_and_never_replaced_with_zero(self) -> None:
        normalizer = FactorServiceFinancialNormalizer(
            (
                contract(
                    "ths_total_assets_stock",
                    value_basis=FinancialValueBasis.POINT_IN_TIME,
                ),
                contract(
                    "ths_total_liabilities_stock",
                    value_basis=FinancialValueBasis.POINT_IN_TIME,
                ),
            )
        )
        batch = normalizer.normalize(
            work_unit=unit(),
            provider_records=(
                {
                    "scode": "600000",
                    "report_period_end": "2024-12-31",
                    "ths_total_assets_stock": Decimal(10),
                    "ths_total_liabilities_stock": None,
                },
            ),
            evidence=raw_object(),
            retrieved_at=NOW,
        )
        self.assertEqual(len(batch.rows), 1)
        self.assertEqual(batch.missing_value_count, 1)
        self.assertEqual(batch.rows[0].provider_field, "ths_total_assets_stock")
        self.assertNotEqual(batch.rows[0].raw_value, Decimal(0))

    def test_float_duplicate_or_out_of_scope_provider_data_fails_closed(self) -> None:
        normalizer = FactorServiceFinancialNormalizer(
            (
                contract(
                    "ths_total_assets_stock",
                    value_basis=FinancialValueBasis.POINT_IN_TIME,
                ),
            )
        )
        base = {
            "scode": "600000",
            "report_period_end": "2024-12-31",
            "ths_total_assets_stock": Decimal(10),
        }
        with self.assertRaisesRegex(TypeError, "float"):
            normalizer.normalize(
                work_unit=unit(),
                provider_records=({**base, "ths_total_assets_stock": 10.0},),
                evidence=raw_object(),
                retrieved_at=NOW,
            )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            normalizer.normalize(
                work_unit=unit(),
                provider_records=(base, base),
                evidence=raw_object(),
                retrieved_at=NOW,
            )
        with self.assertRaisesRegex(ValueError, "outside"):
            normalizer.normalize(
                work_unit=unit(),
                provider_records=({**base, "scode": "600001"},),
                evidence=raw_object(),
                retrieved_at=NOW,
            )


class StubFactorServiceReader:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def iter_v2_table_rows(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        yield from self.rows


class RecordingEvidenceCapture:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def capture_provider_response(self, **kwargs: object) -> RawObject:
        self.calls.append(tuple(sorted(kwargs)))
        return raw_object()


class FactorServiceFinancialSourceTest(unittest.TestCase):
    def test_source_uses_explicit_primary_key_period_cache_ack_and_evidence_capture(self) -> None:
        reader = StubFactorServiceReader(
            (
                {
                    "scode": "600000",
                    "report_period_end": "2024-12-31",
                    "ths_total_assets_stock": Decimal(10),
                },
            )
        )
        capture = RecordingEvidenceCapture()
        source = FactorServiceFinancialSource(
            client=reader,
            normalizer=FactorServiceFinancialNormalizer(
                (
                    contract(
                        "ths_total_assets_stock",
                        value_basis=FinancialValueBasis.POINT_IN_TIME,
                    ),
                )
            ),
            evidence_capture=capture,
            evidence_source_url="https://factor.example.internal/api/v2/table/query",
            clock=lambda: NOW,
        )

        batch = source.fetch(unit(), allow_read_through_cache=True)

        request = reader.calls[0]
        self.assertEqual(request["table_name"], "balance_sheet")
        self.assertEqual(request["primary_key_name"], "scode")
        self.assertEqual(request["primary_key_values"], ("600000",))
        self.assertEqual(
            request["columns"],
            ("scode", "report_period_end", "ths_total_assets_stock"),
        )
        self.assertEqual(request["start_date"], "2024-12-31")
        self.assertTrue(request["allow_read_through_cache"])
        self.assertEqual(len(capture.calls), 1)
        self.assertEqual(batch.raw_object_id, raw_object().raw_object_id)


if __name__ == "__main__":
    unittest.main()
