import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from a_share_platform.adapters.providers.backfill_payloads import DailyObservationPayload
from a_share_platform.adapters.providers.futu_backfill import FutuQuoteBackfillSource
from a_share_platform.adapters.providers.futu_quote import FutuQuoteDailyReader
from a_share_platform.application.backfill import (
    BackfillPlanner,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import BackfillDataDomain
from a_share_platform.domain.pit import DataTrustState

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError(orient)
        return self.rows


class FakeQuoteContext:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def request_history_kline(self, **kwargs: object) -> tuple[int, FakeFrame, object | None]:
        self.calls.append(kwargs)
        return (
            0,
            FakeFrame(
                [
                    {
                        "code": "SH.600519",
                        "time_key": "2018-01-02 00:00:00",
                        "open": 700.0,
                        "high": 710.0,
                        "low": 699.0,
                        "close": 705.0,
                        "last_close": 697.49,
                        "volume": 4961248,
                        "turnover": 3497193408.0,
                    }
                ]
            ),
            None,
        )

    def close(self) -> None:
        self.closed = True


class FakeFutuModule:
    RET_OK = 0

    class KLType:
        K_DAY = "K_DAY"

    class AuType:
        NONE = "NONE"

    def __init__(self) -> None:
        self.context = FakeQuoteContext()

    def OpenQuoteContext(self, **kwargs: object) -> FakeQuoteContext:
        self.context = FakeQuoteContext(**kwargs)
        return self.context


class FutuQuoteProviderTest(unittest.TestCase):
    def test_reader_uses_unadjusted_read_only_quote_api_and_records_provenance(self) -> None:
        module = FakeFutuModule()
        reader = FutuQuoteDailyReader(
            module_loader=lambda _name: module,
            clock=lambda: NOW,
        )
        result = reader.fetch_raw_daily_rows(
            code="SH.600519",
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 5),
        )
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.metadata.provider_id, "futu_quote")
        self.assertEqual(result.metadata.cutoff_date, date(2018, 1, 2))
        self.assertEqual(result.metadata.adjustment_mode, "unadjusted")
        self.assertIn(("volume", "shares"), result.metadata.units)
        self.assertTrue(any("private local" in item for item in result.metadata.warnings))
        self.assertEqual(module.context.calls[0]["autype"], "NONE")
        self.assertTrue(module.context.closed)

    def test_source_never_mentions_or_constructs_a_trade_context(self) -> None:
        path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "a_share_platform"
            / "adapters"
            / "providers"
            / "futu_quote.py"
        )
        source = path.read_text(encoding="utf-8")
        forbidden = "Trade" + "Context"
        self.assertNotIn(forbidden, source)
        self.assertIn("OpenQuoteContext", source)

    def test_quote_reader_can_stage_explicit_private_local_raw_bars(self) -> None:
        module = FakeFutuModule()
        reader = FutuQuoteDailyReader(
            module_loader=lambda _name: module,
            clock=lambda: NOW,
        )
        source = FutuQuoteBackfillSource(reader=reader)
        plan = build_private_local_backfill_plan(
            plan_id="private:futu:v1",
            provider_id="futu_quote",
            symbols=("SH.600519",),
            domains=(BackfillDataDomain.RAW_DAILY_BAR,),
            start_date=date(2018, 1, 1),
            end_date=date(2018, 1, 5),
            created_at=NOW,
        )
        unit = BackfillPlanner().work_units(plan)[0]

        batch = source.fetch(unit, plan)

        self.assertIsInstance(batch.payload, DailyObservationPayload)
        self.assertEqual(batch.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(batch.metadata.provider_id, "futu_quote")
        self.assertTrue(any("private local" in item for item in batch.metadata.warnings))
        self.assertEqual(module.context.calls[0]["autype"], "NONE")


if __name__ == "__main__":
    unittest.main()
