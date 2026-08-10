import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.adapters.providers.akshare_market_structure import (
    CninfoMarketStructureNormalizer,
)
from a_share_platform.domain.security_master import Exchange


class CninfoMarketStructureNormalizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = CninfoMarketStructureNormalizer()

    def test_normalizes_cninfo_share_change_shape_without_inventing_free_float(self) -> None:
        payload = self.normalizer.share_capital(
            code="SZ.000858",
            records=(
                {
                    "证券代码": "000858",
                    "公告日期": date(2024, 5, 11),
                    "变动日期": date(2024, 5, 10),
                    "变动原因": "股权激励限售股上市",
                    "总股本": 3_881_608_005,
                    "已流通股份": 3_800_000_000,
                    "流通受限股份": 81_608_005,
                },
            ),
        )

        self.assertEqual(len(payload.rows), 1)
        row = payload.rows[0]
        self.assertEqual(row.exchange, Exchange.XSHE)
        self.assertEqual(row.total_shares, Decimal(3881608005))
        self.assertEqual(row.circulating_shares, Decimal(3800000000))
        self.assertEqual(row.restricted_shares, Decimal(81608005))
        self.assertIsNone(row.free_float_shares)
        self.assertEqual(row.source_id, "akshare.stock_share_change_cninfo")

    def test_share_change_code_mismatch_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "code mismatch"):
            self.normalizer.share_capital(
                code="SZ.000858",
                records=(
                    {
                        "证券代码": "000001",
                        "公告日期": date(2024, 5, 11),
                        "变动日期": date(2024, 5, 10),
                        "总股本": 1,
                    },
                ),
            )

    def test_normalizes_per_ten_distribution_terms_to_per_share(self) -> None:
        payload = self.normalizer.corporate_actions(
            code="SZ.000858",
            records=(
                {
                    "实施方案公告日期": date(2024, 6, 15),
                    "分红类型": "年度分红",
                    "送股比例": 1,
                    "转增比例": 2,
                    "派息比例": Decimal("4.67"),
                    "股权登记日": date(2024, 6, 20),
                    "除权日": date(2024, 6, 21),
                    "报告时间": "2023-12-31",
                },
            ),
        )

        row = payload.rows[0]
        self.assertEqual(row.bonus_shares_per_share, Decimal("0.1"))
        self.assertEqual(row.capitalization_shares_per_share, Decimal("0.2"))
        self.assertEqual(row.cash_per_share, Decimal("0.467"))
        self.assertEqual(row.currency, "CNY")
        self.assertEqual(row.source_id, "akshare.stock_dividend_cninfo")

    def test_zero_distribution_is_not_turned_into_a_zero_valued_action(self) -> None:
        payload = self.normalizer.corporate_actions(
            code="SH.600519",
            records=(
                {
                    "实施方案公告日期": date(2024, 6, 15),
                    "送股比例": 0,
                    "转增比例": 0,
                    "派息比例": 0,
                    "股权登记日": None,
                    "除权日": None,
                },
            ),
        )

        self.assertEqual(payload.rows, ())

    def test_provider_record_ids_are_stable_across_input_order(self) -> None:
        rows = (
            {
                "证券代码": "000858",
                "公告日期": date(2024, 5, 11),
                "变动日期": date(2024, 5, 10),
                "总股本": 100,
            },
            {
                "证券代码": "000858",
                "公告日期": date(2023, 5, 11),
                "变动日期": date(2023, 5, 10),
                "总股本": 90,
            },
        )

        forward = self.normalizer.share_capital(code="SZ.000858", records=rows)
        backward = self.normalizer.share_capital(code="SZ.000858", records=rows[::-1])

        self.assertEqual(
            {row.provider_record_id for row in forward.rows},
            {row.provider_record_id for row in backward.rows},
        )


if __name__ == "__main__":
    unittest.main()
