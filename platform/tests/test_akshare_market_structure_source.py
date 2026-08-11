import unittest
from collections.abc import Callable
from datetime import UTC, date, datetime

from a_share_platform.adapters.providers.akshare_market_structure_source import (
    AkshareMarketStructureSource,
)
from a_share_platform.adapters.providers.backfill_payloads import (
    CorporateActionPayload,
    SecurityMasterPayload,
    ShareCapitalPayload,
)
from a_share_platform.application.backfill import (
    BackfillPlanner,
    BackfillService,
    build_private_local_backfill_plan,
)
from a_share_platform.domain.backfill import BackfillDataDomain, DatasetQualityStatus
from a_share_platform.domain.security_master import Board, Exchange

NOW = datetime(2026, 8, 11, 2, 0, tzinfo=UTC)


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        if orient != "records":
            raise AssertionError(orient)
        return self._rows


class FakeAkshare:
    def __init__(self) -> None:
        self.share_calls: list[tuple[str, str, str]] = []
        self.dividend_calls: list[str] = []
        self.bse_calls = 0
        self.profile_calls: list[str] = []

    def stock_share_change_cninfo(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> FakeFrame:
        self.share_calls.append((symbol, start_date, end_date))
        return FakeFrame(
            [
                {
                    "证券代码": symbol,
                    "公告日期": date(2018, 5, 11),
                    "变动日期": date(2018, 5, 10),
                    "变动原因": "股权激励限售股上市",
                    "总股本": 100,
                    "已流通股份": 80,
                    "流通受限股份": 20,
                },
                {
                    "证券代码": symbol,
                    "公告日期": date(2019, 6, 11),
                    "变动日期": date(2019, 6, 10),
                    "变动原因": "股份变动",
                    "总股本": 110,
                    "已流通股份": 90,
                    "流通受限股份": 20,
                },
            ]
        )

    def stock_dividend_cninfo(self, *, symbol: str) -> FakeFrame:
        self.dividend_calls.append(symbol)
        return FakeFrame(
            [
                {
                    "实施方案公告日期": date(2018, 6, 15),
                    "分红类型": "年度分红",
                    "送股比例": 0,
                    "转增比例": 0,
                    "派息比例": 5,
                    "股权登记日": date(2018, 6, 20),
                    "除权日": date(2018, 6, 21),
                    "报告时间": "2017-12-31",
                },
                {
                    "实施方案公告日期": date(2019, 6, 15),
                    "分红类型": "年度分红",
                    "送股比例": 1,
                    "转增比例": 0,
                    "派息比例": 4,
                    "股权登记日": date(2019, 6, 20),
                    "除权日": date(2019, 6, 21),
                    "报告时间": "2018-12-31",
                },
            ]
        )

    def stock_info_bj_name_code(self) -> FakeFrame:
        self.bse_calls += 1
        return FakeFrame(
            [
                {
                    "证券代码": "430047",
                    "证券简称": "诺思兰德",
                    "总股本": 274271732,
                    "流通股本": 177000000,
                    "上市日期": date(2020, 11, 24),
                    "所属行业": "医药制造业",
                    "地区": "北京",
                    "报告日期": date(2026, 8, 8),
                }
            ]
        )

    def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
        self.profile_calls.append(symbol)
        return FakeFrame(
            [
                {
                    "公司名称": "北京诺思兰德生物技术股份有限公司",
                    "A股代码": symbol,
                    "上市日期": date(2020, 11, 24),
                }
            ]
        )


def plan_for(domain: BackfillDataDomain, *symbols: str):
    return build_private_local_backfill_plan(
        plan_id=f"private:akshare:{domain.value}:v1",
        provider_id="akshare",
        symbols=tuple(symbols),
        domains=(domain,),
        start_date=date(2018, 1, 1),
        end_date=date(2019, 12, 31),
        created_at=NOW,
    )


class AkshareMarketStructureSourceTest(unittest.TestCase):
    def source(
        self,
        module: object | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> AkshareMarketStructureSource:
        return AkshareMarketStructureSource(
            clock=clock or (lambda: NOW),
            akshare_module_loader=lambda _name: module or FakeAkshare(),
            minimum_interval_seconds=0,
            sleeper=lambda _seconds: None,
        )

    def test_share_capital_fetches_once_per_symbol_and_filters_annual_checkpoints(self) -> None:
        module = FakeAkshare()
        source = self.source(module)
        plan = plan_for(BackfillDataDomain.SHARE_CAPITAL, "SZ.000858")
        units = BackfillPlanner().work_units(plan)

        first = source.fetch(units[0], plan)
        second = source.fetch(units[1], plan)

        self.assertEqual(module.share_calls, [("000858", "20180101", "20191231")])
        self.assertIsInstance(first.payload, ShareCapitalPayload)
        self.assertIsInstance(second.payload, ShareCapitalPayload)
        self.assertEqual(first.row_count, 1)
        self.assertEqual(second.row_count, 1)
        self.assertEqual(first.metadata.provider_id, "akshare")
        self.assertEqual(first.metadata.adjustment_mode, "not_applicable")
        BackfillService._validate_batch(plan, units[0], first)

    def test_cached_response_preserves_original_provider_retrieval_time(self) -> None:
        module = FakeAkshare()
        later = datetime(2026, 8, 11, 3, 0, tzinfo=UTC)
        times = iter((NOW, later))
        source = self.source(module, clock=lambda: next(times))
        plan = plan_for(BackfillDataDomain.SHARE_CAPITAL, "SZ.000858")
        units = BackfillPlanner().work_units(plan)

        first = source.fetch(units[0], plan)
        second = source.fetch(units[1], plan)

        self.assertEqual(first.metadata.retrieved_at, NOW)
        self.assertEqual(second.metadata.retrieved_at, NOW)

    def test_corporate_actions_are_cached_and_keep_zero_observation_explicit(self) -> None:
        module = FakeAkshare()
        source = self.source(module)
        plan = plan_for(BackfillDataDomain.CORPORATE_ACTION, "SH.600519")
        units = BackfillPlanner().work_units(plan)

        first = source.fetch(units[0], plan)
        second = source.fetch(units[1], plan)

        self.assertEqual(module.dividend_calls, ["600519"])
        self.assertIsInstance(first.payload, CorporateActionPayload)
        self.assertIsInstance(second.payload, CorporateActionPayload)
        self.assertEqual(first.row_count, 1)
        self.assertEqual(second.row_count, 1)
        self.assertEqual(first.quality_status, DatasetQualityStatus.PASSED)
        BackfillService._validate_batch(plan, units[1], second)

    def test_xbse_identity_requires_exact_legal_company_profile(self) -> None:
        module = FakeAkshare()
        source = self.source(module)
        plan = plan_for(BackfillDataDomain.SECURITY_MASTER, "BJ.430047")
        unit = BackfillPlanner().work_units(plan)[0]

        batch = source.fetch(unit, plan)

        self.assertEqual(module.bse_calls, 1)
        self.assertEqual(module.profile_calls, ["430047"])
        self.assertIsInstance(batch.payload, SecurityMasterPayload)
        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        row = payload.rows[0]
        self.assertEqual(row.company_legal_name, "北京诺思兰德生物技术股份有限公司")
        self.assertEqual(row.exchange, Exchange.XBSE)
        self.assertEqual(row.board, Board.BSE)
        self.assertEqual(row.industry_name, "医药制造业")
        self.assertEqual(batch.expected_rows, 1)
        BackfillService._validate_batch(plan, unit, batch)

    def test_xbse_profile_code_mismatch_fails_closed(self) -> None:
        class Mismatch(FakeAkshare):
            def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
                return FakeFrame([{"公司名称": "错误公司", "A股代码": "430048"}])

        plan = plan_for(BackfillDataDomain.SECURITY_MASTER, "BJ.430047")
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaisesRegex(RuntimeError, "profile code mismatch"):
            self.source(Mismatch()).fetch(unit, plan)

    def test_explicit_xshe_identity_uses_cninfo_profile_without_bse_list_probe(self) -> None:
        class XsheProfile(FakeAkshare):
            def stock_profile_cninfo(self, *, symbol: str) -> FakeFrame:
                self.profile_calls.append(symbol)
                return FakeFrame(
                    [
                        {
                            "公司名称": "中航成飞股份有限公司",
                            "A股代码": "302132",
                            "A股简称": "中航成飞",
                            "上市日期": date(2010, 8, 27),
                            "所属市场": "深交所创业板",
                            "所属行业": "计算机、通信和其他电子设备制造业",
                        }
                    ]
                )

        module = XsheProfile()
        source = self.source(module)
        plan = plan_for(BackfillDataDomain.SECURITY_MASTER, "SZ.302132")
        unit = BackfillPlanner().work_units(plan)[0]

        batch = source.fetch(unit, plan)

        self.assertEqual(module.bse_calls, 0)
        self.assertEqual(module.profile_calls, ["302132"])
        payload = batch.payload
        assert isinstance(payload, SecurityMasterPayload)
        row = payload.rows[0]
        self.assertEqual(row.company_legal_name, "中航成飞股份有限公司")
        self.assertEqual(row.security_name, "中航成飞")
        self.assertEqual(row.exchange, Exchange.XSHE)
        self.assertEqual(row.board, Board.CHINEXT)
        self.assertEqual(row.listed_on, date(2010, 8, 27))
        self.assertEqual(batch.expected_rows, 1)
        BackfillService._validate_batch(plan, unit, batch)

    def test_non_xbse_all_market_identity_remains_blocked(self) -> None:
        plan = build_private_local_backfill_plan(
            plan_id="private:akshare:xshe-all:v1",
            provider_id="akshare",
            symbols=(),
            all_a_share=True,
            markets=("XSHE",),
            domains=(BackfillDataDomain.SECURITY_MASTER,),
            start_date=date(2018, 1, 1),
            end_date=date(2026, 8, 10),
            created_at=NOW,
        )
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaisesRegex(RuntimeError, "explicit symbols"):
            self.source(FakeAkshare()).fetch(unit, plan)

    def test_source_rejects_unsupported_domain_before_provider_access(self) -> None:
        module = FakeAkshare()
        plan = plan_for(BackfillDataDomain.RAW_DAILY_BAR, "SZ.000858")
        unit = BackfillPlanner().work_units(plan)[0]

        with self.assertRaisesRegex(RuntimeError, "does not implement"):
            self.source(module).fetch(unit, plan)
        self.assertEqual(module.share_calls, [])
        self.assertEqual(module.dividend_calls, [])


if __name__ == "__main__":
    unittest.main()
