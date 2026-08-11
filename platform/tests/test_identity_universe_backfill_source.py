import tempfile
import time
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from a_share_platform.adapters.providers.backfill_payloads import (
    SecurityMasterPayload,
    UniverseMembershipPayload,
)
from a_share_platform.adapters.providers.baostock_backfill import (
    ProviderBackfillUnavailable,
)
from a_share_platform.adapters.providers.baostock_guard import BaostockGuard
from a_share_platform.adapters.providers.identity_universe_backfill import (
    IdentityUniverseBackfillSource,
)
from a_share_platform.adapters.providers.official_delisted_identities import (
    CSI_HISTORICAL_DELISTED_IDENTITIES,
)
from a_share_platform.application.backfill import (
    BackfillPlanner,
    BackfillService,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import (
    BackfillDataDomain,
    UniverseObservationMode,
)
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
        if symbol == "689009":
            return FakeFrame(
                [
                    {
                        "公司名称": "九号有限公司",
                        "A股代码": None,
                        "所属市场": "上交所科创板",
                        "上市日期": "2020-10-29",
                    }
                ]
            )
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


def explicit_identity_plan(*symbols: str, domain: BackfillDataDomain = BackfillDataDomain.SECURITY_MASTER):
    return build_private_local_backfill_plan(
        plan_id=f"private:{domain.value}:explicit:v1",
        provider_id="a_share_identity_universe",
        symbols=tuple(symbols),
        all_a_share=False,
        domains=(domain,),
        start_date=date(2018, 1, 1),
        end_date=date(2018, 1, 3),
        created_at=NOW,
    )


class IdentityUniverseBackfillSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

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
            "baostock_guard": BaostockGuard(
                state_directory=Path(self.temp.name),
                clock=lambda: NOW,
                minimum_interval_seconds=0,
            ),
        }
        options.update(overrides)
        return IdentityUniverseBackfillSource(  # type: ignore[arg-type]
            baostock_module_loader=lambda _name: baostock or FakeBaostock(),
            akshare_module_loader=lambda _name: akshare or FakeAkshare(),
            clock=lambda: NOW,
            **options,
        )

    def test_full_market_security_master_preserves_legal_name_listing_and_industry(self) -> None:
        guard = BaostockGuard(
            state_directory=Path(self.temp.name),
            clock=lambda: NOW,
            minimum_interval_seconds=0,
        )
        plan = plan_for(BackfillDataDomain.SECURITY_MASTER)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.market == "XSHG"
        )

        batch = self.source(baostock_guard=guard).fetch(unit, plan)

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
        self.assertEqual(
            [item.operation for item in guard.attempts(date(2026, 8, 10))],
            ["login", "query_stock_basic", "query_stock_industry", "logout"],
        )
        BackfillService._validate_batch(plan, unit, batch)

    def test_explicit_security_master_fetches_only_requested_symbols(self) -> None:
        plan = explicit_identity_plan("SH.600519")
        unit = BackfillPlanner().work_units(plan)[0]

        batch = self.source().fetch(unit, plan)

        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        self.assertEqual([row.code for row in payload.rows], ["SH.600519"])
        self.assertEqual(batch.expected_rows, 1)
        self.assertEqual(batch.row_count, 1)
        BackfillService._validate_batch(plan, unit, batch)

    def test_star_market_cdr_identity_is_not_dropped(self) -> None:
        class StarCdrBasic(FakeBaostock):
            def query_stock_basic(self) -> FakeResult:
                return FakeResult(
                    ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                    [["sh.689009", "九号公司-WD", "2020-10-29", "", "1", "1"]],
                )

        plan = explicit_identity_plan("SH.689009")
        unit = BackfillPlanner().work_units(plan)[0]

        batch = self.source(baostock=StarCdrBasic()).fetch(unit, plan)

        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        self.assertEqual([row.code for row in payload.rows], ["SH.689009"])
        self.assertEqual(payload.rows[0].board, Board.STAR)
        BackfillService._validate_batch(plan, unit, batch)

    def test_cdr_profile_without_code_requires_matching_market_and_listing_date(self) -> None:
        class MismatchedCdrProfile:
            def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
                return FakeFrame(
                    [
                        {
                            "公司名称": "九号有限公司",
                            "A股代码": None,
                            "所属市场": "上交所科创板",
                            "上市日期": "2020-10-30",
                        }
                    ]
                )

        class StarCdrBasic(FakeBaostock):
            def query_stock_basic(self) -> FakeResult:
                return FakeResult(
                    ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                    [["sh.689009", "九号公司-WD", "2020-10-29", "", "1", "1"]],
                )

        plan = explicit_identity_plan("SH.689009")
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaisesRegex(ProviderBackfillUnavailable, "listing date mismatch"):
            self.source(
                baostock=StarCdrBasic(),
                akshare=MismatchedCdrProfile(),
            ).fetch(unit, plan)

    def test_explicit_security_master_requires_every_requested_symbol(self) -> None:
        plan = explicit_identity_plan("SH.600519", "SH.601318")
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaises(ProviderBackfillUnavailable) as caught:
            self.source().fetch(unit, plan)
        self.assertEqual(
            str(caught.exception),
            "security master provider omitted requested symbols: "
            "missing_count=1; missing_symbols=SH.601318",
        )

    def test_explicit_symbols_cannot_fetch_universe(self) -> None:
        plan = explicit_identity_plan("SH.600519", domain=BackfillDataDomain.UNIVERSE)
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaisesRegex(ValueError, "only security_master"):
            self.source().fetch(unit, plan)

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

        with self.assertRaises(ProviderBackfillUnavailable) as caught:
            self.source(akshare=EmptyAkshare()).fetch(unit, plan)
        self.assertIn("coverage", str(caught.exception))
        self.assertIn("missing_legal_name_count=1", str(caught.exception))
        self.assertIn("SH.600519", str(caught.exception))

    def test_official_delisted_evidence_fills_cninfo_profile_gap(self) -> None:
        class DelistedBasic(FakeBaostock):
            def query_stock_basic(self) -> FakeResult:
                return FakeResult(
                    ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                    [
                        [
                            "sh.600068",
                            "葛洲坝",
                            "1997-05-26",
                            "2021-09-13",
                            "1",
                            "0",
                        ]
                    ],
                )

        class EmptyAkshare:
            def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
                raise AssertionError(f"official evidence should avoid CNInfo retry: {symbol}")

        plan = explicit_identity_plan("SH.600068")
        unit = BackfillPlanner().work_units(plan)[0]

        batch = self.source(baostock=DelistedBasic(), akshare=EmptyAkshare()).fetch(
            unit,
            plan,
        )

        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        self.assertEqual(len(payload.rows), 1)
        row = payload.rows[0]
        self.assertEqual(row.company_legal_name, "中国葛洲坝集团股份有限公司")
        self.assertEqual(row.listed_on, date(1997, 5, 26))
        self.assertEqual(row.delisted_on, date(2021, 9, 13))
        self.assertEqual(row.legal_name_source_id, "sse.delisted_company_list")
        self.assertEqual(
            row.identity_source_id,
            "baostock_sdk.query_stock_basic+sse.delisted_company_list",
        )

    def test_official_delist_date_wins_over_provider_last_trading_date(self) -> None:
        class ConflictingDelistedBasic(FakeBaostock):
            def query_stock_basic(self) -> FakeResult:
                return FakeResult(
                    ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                    [
                        [
                            "sz.000413",
                            "ST旭电",
                            "1996-09-25",
                            "2024-10-10",
                            "1",
                            "0",
                        ]
                    ],
                )

        plan = explicit_identity_plan("SZ.000413")
        unit = BackfillPlanner().work_units(plan)[0]

        batch = self.source(baostock=ConflictingDelistedBasic()).fetch(unit, plan)

        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        self.assertEqual(payload.rows[0].delisted_on, date(2024, 10, 11))
        self.assertEqual(batch.quality_status.value, "warned")
        self.assertIn(("official_delisted_date_override", 1), batch.issue_counts)

    def test_official_delisted_evidence_rejects_listing_date_conflict(self) -> None:
        class ConflictingDelistedBasic(FakeBaostock):
            def query_stock_basic(self) -> FakeResult:
                return FakeResult(
                    ["code", "code_name", "ipoDate", "outDate", "type", "status"],
                    [
                        [
                            "sz.000413",
                            "ST旭电",
                            "1996-09-26",
                            "2024-10-11",
                            "1",
                            "0",
                        ]
                    ],
                )

        plan = explicit_identity_plan("SZ.000413")
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaisesRegex(
            ProviderBackfillUnavailable,
            "official delisted identity conflicts",
        ):
            self.source(baostock=ConflictingDelistedBasic()).fetch(unit, plan)

    def test_csi_historical_delisted_evidence_is_complete_and_bounded(self) -> None:
        expected = {
            "SH.600068",
            "SH.600074",
            "SH.600297",
            "SH.600485",
            "SH.600705",
            "SH.600804",
            "SH.600837",
            "SH.601989",
            "SZ.000413",
            "SZ.000046",
            "SZ.000540",
            "SZ.000627",
            "SZ.000671",
            "SZ.000961",
            "SZ.002411",
            "SZ.002450",
            "SH.600086",
            "SH.600122",
            "SH.600240",
            "SH.600260",
            "SH.600270",
            "SH.600277",
            "SH.600291",
            "SH.600317",
            "SH.600393",
            "SH.600466",
            "SH.600565",
            "SH.600614",
            "SH.600687",
            "SH.600811",
            "SH.600823",
            "SH.600978",
            "SH.603056",
            "SZ.000418",
            "SZ.000587",
            "SZ.000662",
            "SZ.000667",
            "SZ.000732",
            "SZ.000806",
            "SZ.000939",
            "SZ.000979",
            "SZ.002002",
            "SZ.002013",
            "SZ.002018",
            "SZ.002118",
            "SZ.002147",
            "SZ.002280",
            "SZ.002308",
            "SZ.002325",
            "SZ.002359",
            "SZ.002477",
            "SZ.002503",
            "SZ.002505",
            "SZ.002509",
            "SZ.002665",
            "SZ.002699",
            "SZ.300116",
            "SZ.300156",
            "SZ.300202",
            "SZ.300273",
            "SZ.300297",
            "SZ.300630",
        }

        self.assertEqual(set(CSI_HISTORICAL_DELISTED_IDENTITIES), expected)
        for code, evidence in CSI_HISTORICAL_DELISTED_IDENTITIES.items():
            self.assertEqual(evidence.code, code)
            self.assertLess(evidence.listed_on, evidence.delisted_on)
            self.assertTrue(evidence.legal_name)
            self.assertIn(
                evidence.listing_source_id,
                {"sse.delisted_company_list", "szse.delisted_company_list"},
            )
            if code.startswith("SZ."):
                self.assertTrue(evidence.legal_name_source_id.startswith("cninfo."))
                self.assertIn(code, evidence.legal_name_source_id)

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

    def test_official_302_code_prefix_is_a_chinext_a_share(self) -> None:
        class NewCodeMembership(FakeBaostock):
            def query_hs300_stocks(self, *, date: str) -> FakeResult:
                return FakeResult(
                    ["updateDate", "code", "code_name"],
                    [[date, "sz.302132", "中航成飞"]],
                )

        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        batch = self.source(baostock=NewCodeMembership()).fetch(unit, plan)

        payload = batch.payload
        assert isinstance(payload, UniverseMembershipPayload)
        self.assertEqual({row.code for row in payload.rows}, {"SZ.302132"})
        self.assertEqual(IdentityUniverseBackfillSource._board("SZ.302132"), Board.CHINEXT)

    def test_month_end_mode_queries_only_discrete_dates_and_keeps_gaps(self) -> None:
        class MonthlyCalendar(FakeBaostock):
            def query_trade_dates(self, *, start_date: str, end_date: str) -> FakeResult:
                return FakeResult(
                    ["calendar_date", "is_trading_day"],
                    [
                        ["2018-01-02", "1"],
                        ["2018-01-31", "1"],
                        ["2018-02-01", "1"],
                        ["2018-02-28", "1"],
                    ],
                )

            def query_hs300_stocks(self, *, date: str) -> FakeResult:
                self.universe_calls.append(("000300", date))
                return FakeResult(
                    ["updateDate", "code", "code_name"],
                    [[date, "sh.600519", "贵州茅台"]],
                )

        plan = build_private_local_backfill_plan(
            plan_id="private:universe:monthly:v1",
            provider_id="a_share_identity_universe",
            symbols=(),
            all_a_share=True,
            domains=(BackfillDataDomain.UNIVERSE,),
            universe_benchmark_codes=("000300",),
            start_date=date(2018, 1, 1),
            end_date=date(2018, 2, 28),
            created_at=NOW,
            universe_observation_mode=(
                UniverseObservationMode.DISCRETE_MONTH_END
            ),
        )
        unit = BackfillPlanner().work_units(plan)[0]
        baostock = MonthlyCalendar()

        batch = self.source(baostock=baostock).fetch(unit, plan)

        payload = batch.payload
        assert isinstance(payload, UniverseMembershipPayload)
        self.assertEqual(
            baostock.universe_calls,
            [("000300", "2018-01-31"), ("000300", "2018-02-28")],
        )
        self.assertEqual(
            payload.observation_mode,
            UniverseObservationMode.DISCRETE_MONTH_END,
        )
        self.assertEqual(
            payload.observed_dates,
            (date(2018, 1, 31), date(2018, 2, 28)),
        )
        self.assertEqual(
            payload.unobserved_intervals,
            (
                (date(2018, 1, 1), date(2018, 1, 31)),
                (date(2018, 2, 1), date(2018, 2, 28)),
            ),
        )
        self.assertEqual(
            {(row.valid_from, row.valid_to) for row in payload.rows},
            {
                (date(2018, 1, 31), date(2018, 2, 1)),
                (date(2018, 2, 28), date(2018, 3, 1)),
            },
        )
        self.assertTrue(
            all("month_end_discrete" in row.source_id for row in payload.rows)
        )
        self.assertTrue(
            any("does not imply continuity" in item for item in batch.metadata.warnings)
        )

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

    def test_provider_timeout_waits_for_call_before_logout(self) -> None:
        class HangingMembership(FakeBaostock):
            def __init__(self) -> None:
                super().__init__()
                self.events: list[str] = []

            def query_hs300_stocks(self, *, date: str) -> FakeResult:
                self.events.append("query_started")
                time.sleep(0.05)
                result = super().query_hs300_stocks(date=date)
                self.events.append("query_finished")
                return result

            def logout(self) -> None:
                self.events.append("logout")

        plan = plan_for(BackfillDataDomain.UNIVERSE)
        unit = next(
            item
            for item in BackfillPlanner().work_units(plan)
            if item.scope_id == "index:000300"
        )

        baostock = HangingMembership()
        with self.assertRaisesRegex(ProviderBackfillUnavailable, "timed out"):
            self.source(baostock=baostock, call_timeout_seconds=0.001).fetch(
                unit, plan
            )
        self.assertEqual(baostock.events, ["query_started", "query_finished", "logout"])

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
