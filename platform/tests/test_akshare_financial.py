import unittest
from datetime import UTC, date, datetime
from decimal import Decimal

from a_share_platform.adapters.providers.akshare_financial import (
    AkShareFieldContract,
    AkShareFinancialNormalizer,
    AkShareFinancialSource,
    AkShareRateLimitedRequestExecutor,
)
from a_share_platform.domain.disclosure import (
    RawObject,
    RawObjectKind,
    RetentionPolicy,
)
from a_share_platform.domain.financial_backfill import FinancialBackfillWorkUnit
from a_share_platform.domain.financial_sources import (
    AvailabilityMethod,
    FinancialStatementScope,
    FinancialValueBasis,
    ReportVersionType,
)
from a_share_platform.domain.metrics import StatementType
from a_share_platform.domain.pit import DataTrustState, FinancialPeriodType

NOW = datetime(2026, 8, 11, 2, tzinfo=UTC)
HASH = "sha256:" + "a" * 64
SOURCE_URLS = {
    StatementType.BALANCE_SHEET: "https://akshare.akfamily.xyz/data/stock/stock.html",
    StatementType.INCOME_STATEMENT: "https://akshare.akfamily.xyz/data/stock/stock.html",
    StatementType.CASH_FLOW_STATEMENT: "https://akshare.akfamily.xyz/data/stock/stock.html",
}


def unit(
    statement_type: StatementType = StatementType.BALANCE_SHEET,
    provider_table: str = "balance_sheet",
    *,
    symbols: tuple[str, ...] = ("SH.600000",),
    report_period_end: date = date(2024, 12, 31),
) -> FinancialBackfillWorkUnit:
    return FinancialBackfillWorkUnit(
        plan_id="financial-backfill:csi300:akshare:v1",
        checkpoint_key=f"financial:{provider_table}:2024-12-31:bucket-0001",
        provider_id="akshare",
        provider_profile_version="financial-source:akshare-fallback:v1",
        benchmark_id="index:000300",
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="mapping:akshare-eastmoney:v1",
        statement_type=statement_type,
        provider_table=provider_table,
        report_period_end=report_period_end,
        symbol_bucket_id="bucket-0001",
        symbols=symbols,
    )


def raw_object(
    statement_type: StatementType = StatementType.BALANCE_SHEET,
) -> RawObject:
    return RawObject(
        raw_object_id=f"raw:akshare:{statement_type.value}:batch-1",
        object_kind=RawObjectKind.RESPONSE,
        content_hash=HASH,
        source_url=SOURCE_URLS[statement_type],
        provider_id="akshare",
        retrieved_at=NOW,
        media_type="application/json",
        storage_uri=f"memory://akshare/{statement_type.value}/batch-1",
        license_id="license:private-local-research-test",
        retention_policy=RetentionPolicy.INDEFINITE,
        retention_until=None,
        redistribution_allowed=False,
    )


def contract(
    provider_field: str,
    *,
    value_basis: FinancialValueBasis,
    provider_unit: str = "CNY",
    scale: Decimal = Decimal(1),
) -> AkShareFieldContract:
    return AkShareFieldContract(
        provider_field=provider_field,
        provider_unit=provider_unit,
        scale_to_canonical=scale,
        currency="CNY",
        statement_scope=FinancialStatementScope.UNKNOWN,
        value_basis=value_basis,
    )


def record(
    field: str,
    value: object,
    *,
    code: str = "600000",
    report_date: object = "2024-12-31",
    requested_symbol: str = "SH.600000",
) -> dict[str, object]:
    return {
        "__a_share_platform_requested_symbol": requested_symbol,
        "SECURITY_CODE": code,
        "REPORT_DATE": report_date,
        "NOTICE_DATE": "2025-03-28",
        "UPDATE_DATE": "2025-03-29",
        field: value,
    }


class AkShareFinancialNormalizerTest(unittest.TestCase):
    def test_three_statement_wide_rows_preserve_decimal_period_and_value_basis(self) -> None:
        cases = (
            (
                StatementType.BALANCE_SHEET,
                "balance_sheet",
                "TOTAL_ASSETS",
                FinancialValueBasis.POINT_IN_TIME,
                date(2024, 12, 31),
            ),
            (
                StatementType.INCOME_STATEMENT,
                "income_statement",
                "TOTAL_OPERATE_INCOME",
                FinancialValueBasis.CUMULATIVE_YTD,
                date(2024, 1, 1),
            ),
            (
                StatementType.CASH_FLOW_STATEMENT,
                "cash_flow",
                "NETCASH_OPERATE",
                FinancialValueBasis.CUMULATIVE_YTD,
                date(2024, 1, 1),
            ),
        )
        for statement_type, table, field, basis, expected_start in cases:
            with self.subTest(statement_type=statement_type):
                work_unit = unit(statement_type, table)
                batch = AkShareFinancialNormalizer(
                    (contract(field, value_basis=basis),)
                ).normalize(
                    work_unit=work_unit,
                    provider_records=(record(field, "123.45"),),
                    evidence=raw_object(statement_type),
                    retrieved_at=NOW,
                )

                value = batch.rows[0]
                self.assertEqual(value.raw_value, Decimal("123.45"))
                self.assertEqual(value.statement_type, statement_type)
                self.assertEqual(value.period_type, FinancialPeriodType.ANNUAL)
                self.assertEqual(value.value_basis, basis)
                self.assertEqual(value.report_period_start, expected_start)
                self.assertEqual(value.statement_scope, FinancialStatementScope.UNKNOWN)
                self.assertEqual(value.report_version_type, ReportVersionType.UNKNOWN)
                self.assertEqual(value.availability_method, AvailabilityMethod.CONSERVATIVE_RETRIEVAL_TIME)
                self.assertEqual(value.available_at, NOW)
                self.assertIsNone(value.announced_at)
                self.assertIsNone(value.provider_updated_at)
                self.assertTrue(any("NOTICE_DATE is date-only" in item for item in value.warnings))
                self.assertTrue(any("UPDATE_DATE is date-only" in item for item in value.warnings))
                self.assertEqual(batch.trust_state, DataTrustState.NORMALIZED_CURRENT)

    def test_missing_values_are_counted_and_never_replaced_with_zero(self) -> None:
        normalizer = AkShareFinancialNormalizer(
            (
                contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),
                contract("TOTAL_LIABILITIES", value_basis=FinancialValueBasis.POINT_IN_TIME),
                contract("TOTAL_EQUITY", value_basis=FinancialValueBasis.POINT_IN_TIME),
            )
        )
        provider_record = record("TOTAL_ASSETS", "10")
        provider_record["TOTAL_LIABILITIES"] = "--"
        provider_record["TOTAL_EQUITY"] = float("nan")

        batch = normalizer.normalize(
            work_unit=unit(),
            provider_records=(provider_record,),
            evidence=raw_object(),
            retrieved_at=NOW,
        )

        self.assertEqual(len(batch.rows), 1)
        self.assertEqual(batch.missing_value_count, 2)
        self.assertEqual(batch.rows[0].raw_value, Decimal(10))
        self.assertNotEqual(batch.rows[0].raw_value, Decimal(0))

    def test_finite_dataframe_float_is_explicitly_converted_and_warned(self) -> None:
        batch = AkShareFinancialNormalizer(
            (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
        ).normalize(
            work_unit=unit(),
            provider_records=(record("TOTAL_ASSETS", 123.45),),
            evidence=raw_object(),
            retrieved_at=NOW,
        )

        self.assertEqual(batch.rows[0].raw_value, Decimal("123.45"))
        self.assertTrue(
            any("binary float" in warning for warning in batch.rows[0].warnings)
        )

    def test_revenue_provider_field_is_not_aliased_to_a_different_source_definition(self) -> None:
        batch = AkShareFinancialNormalizer(
            (
                contract(
                    "TOTAL_OPERATE_INCOME",
                    value_basis=FinancialValueBasis.CUMULATIVE_YTD,
                ),
            )
        ).normalize(
            work_unit=unit(StatementType.INCOME_STATEMENT, "income_statement"),
            provider_records=(record("TOTAL_OPERATE_INCOME", "150560330316.45"),),
            evidence=raw_object(StatementType.INCOME_STATEMENT),
            retrieved_at=NOW,
        )

        provider_row = batch.rows[0]
        self.assertEqual(provider_row.provider_field, "TOTAL_OPERATE_INCOME")
        self.assertTrue(
            any(
                "requires explicit mapping before cross-source comparison" in warning
                for warning in provider_row.warnings
            )
        )

    def test_other_periods_are_retained_in_raw_evidence_scope_but_not_normalized(self) -> None:
        normalizer = AkShareFinancialNormalizer(
            (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
        )
        batch = normalizer.normalize(
            work_unit=unit(),
            provider_records=(
                record("TOTAL_ASSETS", "9", report_date="2023-12-31"),
                record("TOTAL_ASSETS", "10"),
            ),
            evidence=raw_object(),
            retrieved_at=NOW,
        )

        self.assertEqual(batch.provider_record_count, 1)
        self.assertEqual(len(batch.rows), 1)
        self.assertTrue(
            any("rows_outside_requested_period=1" in warning for warning in batch.warnings)
        )

    def test_duplicate_symbol_mismatch_period_and_field_contracts_fail_closed(self) -> None:
        normalizer = AkShareFinancialNormalizer(
            (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
        )
        base = record("TOTAL_ASSETS", "10")
        with self.assertRaisesRegex(ValueError, "duplicate AkShare provider record"):
            normalizer.normalize(
                work_unit=unit(),
                provider_records=(base, base),
                evidence=raw_object(),
                retrieved_at=NOW,
            )
        with self.assertRaisesRegex(ValueError, "does not match requested symbol"):
            normalizer.normalize(
                work_unit=unit(),
                provider_records=(record("TOTAL_ASSETS", "10", code="600001"),),
                evidence=raw_object(),
                retrieved_at=NOW,
            )
        with self.assertRaisesRegex(ValueError, "unsupported A-share financial report period"):
            normalizer.normalize(
                work_unit=unit(),
                provider_records=(record("TOTAL_ASSETS", "10", report_date="2024-11-30"),),
                evidence=raw_object(),
                retrieved_at=NOW,
            )
        with self.assertRaisesRegex(ValueError, "field contracts must be unique"):
            AkShareFinancialNormalizer(
                (
                    contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),
                    contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),
                )
            )


class StubFrame:
    def __init__(self, rows: tuple[dict[str, object], ...]) -> None:
        self.rows = rows
        self.orients: list[str] = []

    def to_dict(self, orient: str):  # type: ignore[no-untyped-def]
        self.orients.append(orient)
        return list(self.rows)


class StubAkShareClient:
    def __init__(self, frames: dict[str, StubFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, str]] = []

    def stock_balance_sheet_by_report_em(self, *, symbol: str) -> StubFrame:
        self.calls.append(("stock_balance_sheet_by_report_em", symbol))
        return self.frames[symbol]

    def stock_profit_sheet_by_report_em(self, *, symbol: str) -> StubFrame:
        self.calls.append(("stock_profit_sheet_by_report_em", symbol))
        return self.frames[symbol]

    def stock_cash_flow_sheet_by_report_em(self, *, symbol: str) -> StubFrame:
        self.calls.append(("stock_cash_flow_sheet_by_report_em", symbol))
        return self.frames[symbol]


class RecordingRequestExecutor:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def execute(self, operation: str, action):  # type: ignore[no-untyped-def]
        self.operations.append(operation)
        return action()


class RecordingEvidenceCapture:
    def __init__(self, statement_type: StatementType) -> None:
        self.statement_type = statement_type
        self.calls: list[dict[str, object]] = []

    def capture_provider_response(self, **kwargs: object) -> RawObject:
        self.calls.append(dict(kwargs))
        return raw_object(self.statement_type)


class AkShareFinancialSourceTest(unittest.TestCase):
    def test_read_through_cache_reuses_one_all_period_response_per_symbol_table(self) -> None:
        frame = StubFrame(
            (
                {
                    "SECURITY_CODE": "600000",
                    "REPORT_DATE": "2024-12-31",
                    "TOTAL_ASSETS": "20",
                },
                {
                    "SECURITY_CODE": "600000",
                    "REPORT_DATE": "2023-12-31",
                    "TOTAL_ASSETS": "10",
                },
            )
        )
        client = StubAkShareClient({"SH600000": frame})
        evidence_capture = RecordingEvidenceCapture(StatementType.BALANCE_SHEET)
        clock_calls = 0

        def clock() -> datetime:
            nonlocal clock_calls
            clock_calls += 1
            return NOW

        source = AkShareFinancialSource(
            client=client,
            normalizer=AkShareFinancialNormalizer(
                (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
            ),
            request_executor=RecordingRequestExecutor(),
            evidence_capture=evidence_capture,
            evidence_source_urls=SOURCE_URLS,
            clock=clock,
        )

        latest = source.fetch(unit(), allow_read_through_cache=True)
        earlier = source.fetch(
            unit(report_period_end=date(2023, 12, 31)),
            allow_read_through_cache=True,
        )

        self.assertEqual(
            client.calls,
            [("stock_balance_sheet_by_report_em", "SH600000")],
        )
        self.assertEqual(frame.orients, ["records"])
        self.assertEqual(clock_calls, 1)
        self.assertEqual(latest.rows[0].raw_value, Decimal(20))
        self.assertEqual(earlier.rows[0].raw_value, Decimal(10))
        self.assertEqual(latest.rows[0].retrieved_at, earlier.rows[0].retrieved_at)
        self.assertEqual(len(evidence_capture.calls), 2)
        self.assertEqual(
            evidence_capture.calls[0]["provider_records"],
            evidence_capture.calls[1]["provider_records"],
        )
        self.assertIsNot(
            evidence_capture.calls[0]["provider_records"],
            evidence_capture.calls[1]["provider_records"],
        )

    def test_cache_bypass_refetches_provider_response(self) -> None:
        frame = StubFrame(
            (
                {
                    "SECURITY_CODE": "600000",
                    "REPORT_DATE": "2024-12-31",
                    "TOTAL_ASSETS": "20",
                },
            )
        )
        client = StubAkShareClient({"SH600000": frame})
        source = AkShareFinancialSource(
            client=client,
            normalizer=AkShareFinancialNormalizer(
                (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
            ),
            request_executor=RecordingRequestExecutor(),
            evidence_capture=RecordingEvidenceCapture(StatementType.BALANCE_SHEET),
            evidence_source_urls=SOURCE_URLS,
            clock=lambda: NOW,
        )

        source.fetch(unit(), allow_read_through_cache=False)
        source.fetch(unit(), allow_read_through_cache=False)

        self.assertEqual(len(client.calls), 2)
        self.assertEqual(frame.orients, ["records", "records"])

    def test_dataframe_calls_are_injected_rate_bounded_and_captured_once(self) -> None:
        frames = {
            "SH600000": StubFrame(
                (
                    {
                        "SECURITY_CODE": "600000",
                        "REPORT_DATE": datetime(2024, 12, 31, tzinfo=UTC),
                        "NOTICE_DATE": date(2025, 3, 28),
                        "UPDATE_DATE": date(2025, 3, 29),
                        "TOTAL_ASSETS": Decimal(10),
                    },
                )
            ),
            "SZ000001": StubFrame(
                (
                    {
                        "SECURITY_CODE": "000001",
                        "REPORT_DATE": "2024-12-31 00:00:00",
                        "NOTICE_DATE": "2025-03-28",
                        "UPDATE_DATE": "2025-03-29",
                        "TOTAL_ASSETS": "20",
                    },
                )
            ),
        }
        client = StubAkShareClient(frames)
        request_executor = RecordingRequestExecutor()
        evidence_capture = RecordingEvidenceCapture(StatementType.BALANCE_SHEET)
        source = AkShareFinancialSource(
            client=client,
            normalizer=AkShareFinancialNormalizer(
                (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
            ),
            request_executor=request_executor,
            evidence_capture=evidence_capture,
            evidence_source_urls=SOURCE_URLS,
            clock=lambda: NOW,
        )

        batch = source.fetch(
            unit(symbols=("SH.600000", "SZ.000001")),
            allow_read_through_cache=False,
        )

        self.assertEqual(
            client.calls,
            [
                ("stock_balance_sheet_by_report_em", "SH600000"),
                ("stock_balance_sheet_by_report_em", "SZ000001"),
            ],
        )
        self.assertEqual(
            request_executor.operations,
            [
                "stock_balance_sheet_by_report_em:SH600000",
                "stock_balance_sheet_by_report_em:SZ000001",
            ],
        )
        self.assertTrue(all(frame.orients == ["records"] for frame in frames.values()))
        self.assertEqual(len(evidence_capture.calls), 1)
        captured = evidence_capture.calls[0]["provider_records"]
        self.assertEqual(len(captured), 2)  # type: ignore[arg-type]
        self.assertEqual(len(batch.rows), 2)
        self.assertEqual(batch.accepted_symbols, ("SH.600000", "SZ.000001"))
        self.assertEqual(batch.trust_state, DataTrustState.NORMALIZED_CURRENT)

    def test_statement_type_selects_one_explicit_akshare_endpoint(self) -> None:
        cases = (
            (
                StatementType.BALANCE_SHEET,
                "balance_sheet",
                "TOTAL_ASSETS",
                FinancialValueBasis.POINT_IN_TIME,
                "stock_balance_sheet_by_report_em",
            ),
            (
                StatementType.INCOME_STATEMENT,
                "income_statement",
                "TOTAL_OPERATE_INCOME",
                FinancialValueBasis.CUMULATIVE_YTD,
                "stock_profit_sheet_by_report_em",
            ),
            (
                StatementType.CASH_FLOW_STATEMENT,
                "cash_flow",
                "NETCASH_OPERATE",
                FinancialValueBasis.CUMULATIVE_YTD,
                "stock_cash_flow_sheet_by_report_em",
            ),
        )
        for statement_type, table, field, basis, expected_operation in cases:
            with self.subTest(statement_type=statement_type):
                frame = StubFrame(
                    (
                        {
                            "SECURITY_CODE": "600000",
                            "REPORT_DATE": "2024-12-31",
                            field: "10",
                        },
                    )
                )
                client = StubAkShareClient({"SH600000": frame})
                capture = RecordingEvidenceCapture(statement_type)
                source = AkShareFinancialSource(
                    client=client,
                    normalizer=AkShareFinancialNormalizer(
                        (contract(field, value_basis=basis),)
                    ),
                    request_executor=RecordingRequestExecutor(),
                    evidence_capture=capture,
                    evidence_source_urls=SOURCE_URLS,
                    clock=lambda: NOW,
                )

                source.fetch(unit(statement_type, table), allow_read_through_cache=False)

                self.assertEqual(client.calls, [(expected_operation, "SH600000")])

    def test_provider_and_statement_table_mismatch_fail_before_client_access(self) -> None:
        client = StubAkShareClient({})
        source = AkShareFinancialSource(
            client=client,
            normalizer=AkShareFinancialNormalizer(
                (contract("TOTAL_ASSETS", value_basis=FinancialValueBasis.POINT_IN_TIME),)
            ),
            request_executor=RecordingRequestExecutor(),
            evidence_capture=RecordingEvidenceCapture(StatementType.BALANCE_SHEET),
            evidence_source_urls=SOURCE_URLS,
            clock=lambda: NOW,
        )
        with self.assertRaisesRegex(ValueError, "provider does not match"):
            source.fetch(
                FinancialBackfillWorkUnit(
                    **{**unit().__dict__, "provider_id": "factor_service_ths"}
                ),
                allow_read_through_cache=False,
            )
        with self.assertRaisesRegex(ValueError, "table does not match"):
            source.fetch(
                unit(StatementType.BALANCE_SHEET, "cash_flow"),
                allow_read_through_cache=False,
            )
        self.assertEqual(client.calls, [])


class FakeTiming:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class AkShareRateLimitedRequestExecutorTest(unittest.TestCase):
    def test_retryable_failure_uses_bounded_retry_and_subsequent_rate_limit(self) -> None:
        timing = FakeTiming()
        executor = AkShareRateLimitedRequestExecutor(
            minimum_interval_seconds=1.0,
            max_attempts=2,
            retry_backoff_seconds=2.0,
            monotonic=timing.monotonic,
            sleep=timing.sleep,
            retryable_errors=(TimeoutError,),
        )
        attempts = 0

        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("temporary provider timeout")
            return "ok"

        self.assertEqual(executor.execute("financial:600000", flaky), "ok")
        self.assertEqual(attempts, 2)
        executor.execute("financial:600001", lambda: "next")
        self.assertEqual(timing.sleeps, [2.0, 1.0])

    def test_non_retryable_and_exhausted_errors_are_not_hidden(self) -> None:
        timing = FakeTiming()
        executor = AkShareRateLimitedRequestExecutor(
            minimum_interval_seconds=0,
            max_attempts=2,
            retry_backoff_seconds=0,
            monotonic=timing.monotonic,
            sleep=timing.sleep,
            retryable_errors=(TimeoutError,),
        )
        with self.assertRaisesRegex(ValueError, "bad schema"):
            executor.execute("schema", lambda: (_ for _ in ()).throw(ValueError("bad schema")))
        with self.assertRaisesRegex(TimeoutError, "still down"):
            executor.execute(
                "timeout",
                lambda: (_ for _ in ()).throw(TimeoutError("still down")),
            )


if __name__ == "__main__":
    unittest.main()
