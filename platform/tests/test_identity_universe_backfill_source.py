import time
import unittest
from datetime import UTC, date, datetime

from a_share_platform.adapters.providers.backfill_payloads import (
    SecurityMasterPayload,
    UniverseMembershipPayload,
)
from a_share_platform.adapters.providers.baostock_backfill import (
    ProviderBackfillUnavailable,
)
from a_share_platform.adapters.providers.identity_universe_backfill import (
    IdentityUniverseBackfillSource,
)
from a_share_platform.application.backfill import (
    BackfillPlanner,
    BackfillService,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import BackfillDataDomain
from a_share_platform.domain.security_master import Board, Exchange

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


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError(orient)
        return self.rows


class FakeAkshare:
    def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
        names = {
            "600519": "贵州茅台酒股份有限公司",
            "000001": "平安银行股份有限公司",
        }
        return FakeFrame([{"公司名称": names[symbol], "A股代码": symbol}])


class FakeBaostock:
    def __init__(self) -> None:
        self.universe_calls: list[tuple[str, str]] = []

    def login(self) -> FakeResult:
        return FakeResult([], [])

    def logout(self) -> None:
        return None

    def query_stock_basic(self) -> FakeResult:
        return FakeResult(
            ["code", "code_name", "ipoDate", "outDate", "type", "status"],
            [
                ["sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"],
                ["sz.000001", "平安银行", "1991-04-03", "", "1", "1"],
                ["sh.000001", "上证指数", "1991-07-15", "", "2", "1"],
            ],
        )

    def query_stock_industry(self, *, date: str) -> FakeResult:
        return FakeResult(
            ["updateDate", "code", "code_name", "industry", "industryClassification"],
            [
                [date, "sh.600519", "贵州茅台", "酒、饮料和精制茶制造业", "证监会行业"],
                [date, "sz.000001", "平安银行", "货币金融服务", "证监会行业"],
            ],
        )

    def query_trade_dates(self, *, start_date: str, end_date: str) -> FakeResult:
        return FakeResult(
            ["calendar_date", "is_trading_day"],
            [["2018-01-02", "1"], ["2018-01-03", "1"]],
        )

    def query_hs300_stocks(self, *, date: str) -> FakeResult:
        self.universe_calls.append(("000300", date))
        members = [[date, "sh.600519", "贵州茅台"]]
        if date == "2018-01-02":
            members.append([date, "sz.000001", "平安银行"])
        return FakeResult(["updateDate", "code", "code_name"], members)

    def query_zz500_stocks(self, *, date: str) -> FakeResult:
        self.universe_calls.append(("000905", date))
        return FakeResult(
            ["updateDate", "code", "code_name"],
            [[date, "sz.000001", "平安银行"]],
        )


def plan_for(domain: BackfillDataDomain):
    return build_private_local_backfill_plan(
        plan_id=f"private:{domain.value}:all:v1",
        provider_id="a_share_identity_universe",
        symbols=(),
        all_a_share=True,
        domains=(domain,),
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 3),
        created_at=NOW,
    )


class IdentityUniverseBackfillSourceTest(unittest.TestCase):
    def source(
        self,
        *,
        baostock: object | None = None,
        akshare: object | None = None,
        **overrides: object,
    ) -> IdentityUniverseBackfillSource:
        options: dict[str, object] = {
            "minimum_security_rows": 1,
            "minimum_security_coverage_ratio": 1.0,
            "membership_cardinality_bounds": {
                "000300": (1, 2),
                "000905": (1, 2),
            },
            "maximum_membership_change_ratio": 1.0,
            "request_interval_seconds": 0,
        }
        options.update(overrides)
        return IdentityUniverseBackfillSource(  # type: ignore[arg-type]
            baostock_module_loader=lambda _name: baostock or FakeBaostock(),
            akshare_module_loader=lambda _name: akshare or FakeAkshare(),
            clock=lambda: NOW,
            **options,
        )

    def test_full_market_security_master_preserves_legal_name_listing_and_industry(self) -> None:
        plan = plan_for(BackfillDataDomain.SECURITY_MASTER)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.market == "XSHG"
        )

        batch = self.source().fetch(unit, plan)

        self.assertIsInstance(batch.payload, SecurityMasterPayload)
        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        self.assertEqual(len(payload.rows), 1)
        row = payload.rows[0]
        self.assertEqual(row.company_legal_name, "贵州茅台酒股份有限公司")
        self.assertEqual(row.security_name, "贵州茅台")
        self.assertEqual(row.exchange, Exchange.XSHG)
        self.assertEqual(row.board, Board.MAIN)
        self.assertEqual(row.industry_name, "酒、饮料和精制茶制造业")
        self.assertEqual(batch.metadata.adjustment_mode, "not_applicable")
        BackfillService._validate_batch(plan, unit, batch)

    def test_security_master_rejects_duplicate_codes(self) -> None:
        class DuplicateBasic(FakeBaostock):
            def query_stock_basic(self) -> FakeResult:
                result = super().query_stock_basic()
                rows: list[list[str]] = []
                while result.next():
                    rows.append(result.get_row_data())
                rows.append(rows[0])
                return FakeResult(list(result.fields), rows)

        plan = plan_for(BackfillDataDomain.SECURITY_MASTER)
        unit = next(
            item for item in BackfillPlanner().work_units(plan) if item.market == "XSHG"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "duplicate codes"):
            self.source(baostock=DuplicateBasic()).fetch(unit, plan)

    def test_security_master_rejects_low_legal_name_coverage(self) -> None:
        class EmptyAkshare:
            def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
                return FakeFrame([])

        plan = plan_for(BackfillDataDomain.SECURITY_MASTER)
        unit = next(
            item for item in BackfillPlanner().work_units(plan) if item.market == "XSHG"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "coverage"):
            self.source(akshare=EmptyAkshare()).fetch(unit, plan)

    def test_cninfo_legal_name_must_match_requested_a_share_code(self) -> None:
        class MismatchedAkshare:
            def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
                return FakeFrame(
                    [{"公司名称": "错误公司股份有限公司", "A股代码": "000001"}]
                )

        plan = plan_for(BackfillDataDomain.SECURITY_MASTER)
        unit = next(
            item for item in BackfillPlanner().work_units(plan) if item.market == "XSHG"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "code mismatch"):
            self.source(akshare=MismatchedAkshare()).fetch(unit, plan)

    def test_daily_index_snapshots_are_compressed_to_non_overlapping_intervals(self) -> None:
        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        batch = self.source().fetch(unit, plan)

        self.assertIsInstance(batch.payload, UniverseMembershipPayload)
        payload = batch.payload
        assert isinstance(payload, UniverseMembershipPayload)
        self.assertEqual(payload.benchmark_code, "000300")
        by_code = {row.code: row for row in payload.rows}
        self.assertEqual(by_code["SZ.000001"].valid_from, date(2018, 1, 2))
        self.assertEqual(by_code["SZ.000001"].valid_to, date(2018, 1, 3))
        self.assertEqual(by_code["SH.600519"].valid_from, date(2018, 1, 2))
        self.assertEqual(by_code["SH.600519"].valid_to, date(2018, 1, 4))
        self.assertEqual(batch.metadata.adjustment_mode, "not_applicable")
        BackfillService._validate_batch(plan, unit, batch)

    def test_empty_daily_index_snapshot_fails_closed(self) -> None:
        class EmptyMembership(FakeBaostock):
            def query_hs300_stocks(self, *, date: str) -> FakeResult:
                return FakeResult(["updateDate", "code", "code_name"], [])

        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "empty snapshot"):
            self.source(baostock=EmptyMembership()).fetch(unit, plan)

    def test_implausible_index_cardinality_fails_closed(self) -> None:
        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "cardinality"):
            self.source(
                membership_cardinality_bounds={"000300": (3, 300), "000905": (1, 2)}
            ).fetch(unit, plan)

    def test_abrupt_index_membership_change_fails_closed(self) -> None:
        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "change ratio"):
            self.source(maximum_membership_change_ratio=0.25).fetch(unit, plan)

    def test_future_membership_update_date_fails_closed(self) -> None:
        class FutureUpdate(FakeBaostock):
            def query_hs300_stocks(self, *, date: str) -> FakeResult:
                return FakeResult(
                    ["updateDate", "code", "code_name"],
                    [["2099-01-01", "sh.600519", "贵州茅台"]],
                )

        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "future updateDate"):
            self.source(baostock=FutureUpdate()).fetch(unit, plan)

    def test_provider_call_timeout_is_bounded(self) -> None:
        class HangingMembership(FakeBaostock):
            def query_hs300_stocks(self, *, date: str) -> FakeResult:
                time.sleep(0.05)
                return super().query_hs300_stocks(date=date)

        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "timed out"):
            self.source(baostock=HangingMembership(), call_timeout_seconds=0.001).fetch(
                unit, plan
            )

    def test_daily_membership_requests_are_rate_limited(self) -> None:
        delays: list[float] = []
        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        self.source(
            sleeper=delays.append,
            request_interval_seconds=0.125,
        ).fetch(unit, plan)

        self.assertEqual(delays, [0.125, 0.125])


if __name__ == "__main__":
    unittest.main()
