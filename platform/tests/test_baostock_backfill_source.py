import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from a_share_platform.adapters.providers.backfill_payloads import (
    DailyObservationPayload,
    TradingCalendarPayload,
)
from a_share_platform.adapters.providers.baostock_backfill import (
    BaostockBackfillSource,
    ProviderBackfillUnavailable,
)
from a_share_platform.adapters.providers.baostock_guard import BaostockGuard
from a_share_platform.application.backfill import (
    BackfillPlanner,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import BackfillDataDomain
from a_share_platform.domain.pit import DataTrustState

NOW = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.error_code = "0"
        self.error_msg = "success"
        self.fields = fields
        self._rows = iter(rows)
        self._current: list[str] | None = None

    def next(self) -> bool:
        try:
            self._current = next(self._rows)
        except StopIteration:
            return False
        return True

    def get_row_data(self) -> list[str]:
        assert self._current is not None
        return self._current


class FakeBaostock:
    def __init__(self) -> None:
        self.history_calls: list[dict[str, object]] = []
        self.calendar_calls: list[dict[str, object]] = []
        self.logged_out = False

    def login(self) -> FakeResult:
        return FakeResult([], [])

    def logout(self) -> None:
        self.logged_out = True

    def query_history_k_data_plus(self, **kwargs: object) -> FakeResult:
        self.history_calls.append(kwargs)
        return FakeResult(
            str(kwargs["fields"]).split(","),
            [[
                "2018-01-02",
                "sh.600519",
                "700.00",
                "710.00",
                "699.00",
                "705.00",
                "697.49",
                "4961248",
                "3497193408.00",
                "1",
                "0",
            ]],
        )

    def query_trade_dates(self, **kwargs: object) -> FakeResult:
        self.calendar_calls.append(kwargs)
        return FakeResult(
            ["calendar_date", "is_trading_day"],
            [["2018-01-01", "0"], ["2018-01-02", "1"]],
        )


def plan_for(domain: BackfillDataDomain):
    return build_private_local_backfill_plan(
        plan_id=f"private:{domain.value}:v1",
        provider_id="baostock_sdk",
        symbols=("SH.600519",),
        domains=(domain,),
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 5),
        created_at=NOW,
    )


class BaostockBackfillSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def guard(self) -> BaostockGuard:
        return BaostockGuard(
            state_directory=Path(self.temp.name),
            clock=lambda: NOW,
            minimum_interval_seconds=0,
        )

    def source(self, module: FakeBaostock, guard: BaostockGuard) -> BaostockBackfillSource:
        return BaostockBackfillSource(
            module_loader=lambda _name: module,
            clock=lambda: NOW,
            baostock_guard=guard,
        )

    def test_fetches_raw_daily_bars_with_unadjusted_flag_and_provenance(self) -> None:
        module = FakeBaostock()
        guard = self.guard()
        plan = plan_for(BackfillDataDomain.RAW_DAILY_BAR)
        unit = BackfillPlanner().work_units(plan)[0]
        source = self.source(module, guard)

        batch = source.fetch(unit, plan)

        self.assertIsInstance(batch.payload, DailyObservationPayload)
        payload = batch.payload
        assert isinstance(payload, DailyObservationPayload)
        self.assertEqual(payload.rows[0].code, "SH.600519")
        self.assertEqual(payload.rows[0].session_date, date(2018, 1, 2))
        self.assertEqual(batch.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(batch.metadata.adjustment_mode, "unadjusted")
        self.assertEqual(module.history_calls[0]["adjustflag"], "3")
        self.assertEqual(module.history_calls[0]["frequency"], "d")
        self.assertTrue(module.logged_out)
        self.assertEqual(
            [item.operation for item in guard.attempts(date(2026, 8, 10))],
            ["login", "query_history_k_data_plus", "logout"],
        )

    def test_fetches_calendar_without_inventing_holiday_names(self) -> None:
        module = FakeBaostock()
        guard = self.guard()
        plan = plan_for(BackfillDataDomain.TRADING_CALENDAR)
        unit = BackfillPlanner().work_units(plan)[0]
        source = self.source(module, guard)

        batch = source.fetch(unit, plan)

        self.assertIsInstance(batch.payload, TradingCalendarPayload)
        self.assertEqual(batch.metadata.adjustment_mode, "not_applicable")
        payload = batch.payload
        assert isinstance(payload, TradingCalendarPayload)
        self.assertFalse(payload.rows[0].is_open)
        self.assertEqual(payload.rows[0].closure_reason, "provider_reported_closed")
        self.assertTrue(payload.rows[1].is_open)
        self.assertEqual(
            [item.operation for item in guard.attempts(date(2026, 8, 10))],
            ["login", "query_trade_dates", "logout"],
        )

    def test_unsupported_domain_is_explicitly_unavailable(self) -> None:
        module = FakeBaostock()
        guard = self.guard()
        plan = plan_for(BackfillDataDomain.CORPORATE_ACTION)
        unit = BackfillPlanner().work_units(plan)[0]
        source = self.source(module, guard)
        with self.assertRaisesRegex(ProviderBackfillUnavailable, "corporate_action"):
            source.fetch(unit, plan)


if __name__ == "__main__":
    unittest.main()
