import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from a_share_platform.adapters.providers.backfill_payloads import (
    CorporateActionPayload,
    ShareCapitalPayload,
    StagedCorporateActionObservation,
    StagedShareCapitalObservation,
)
from a_share_platform.domain.security_master import Exchange


class MarketStructurePayloadTest(unittest.TestCase):
    def setUp(self) -> None:
        self.capital = StagedShareCapitalObservation(
            code="SZ.000858",
            exchange=Exchange.XSHE,
            effective_on=date(2024, 5, 10),
            announced_on=date(2024, 5, 11),
            total_shares=Decimal(3881608005),
            circulating_shares=Decimal(3881608005),
            restricted_shares=Decimal(0),
            free_float_shares=None,
            provider_record_id="cninfo:share-change:000858:2024-05-10",
            source_id="akshare.stock_share_change_cninfo",
        )
        self.distribution = StagedCorporateActionObservation(
            code="SZ.000858",
            exchange=Exchange.XSHE,
            announced_on=date(2024, 6, 15),
            record_date=date(2024, 6, 20),
            ex_date=date(2024, 6, 21),
            cash_per_share=Decimal("0.467"),
            bonus_shares_per_share=None,
            capitalization_shares_per_share=Decimal("0.2"),
            rights_shares_per_share=None,
            rights_subscription_price=None,
            currency="cny",
            provider_record_id="cninfo:dividend:000858:2023:a",
            source_id="akshare.stock_dividend_cninfo",
        )

    def test_share_capital_keeps_provider_dates_and_missing_free_float_explicit(self) -> None:
        payload = ShareCapitalPayload((self.capital,))

        self.assertEqual(payload.rows[0].effective_on, date(2024, 5, 10))
        self.assertEqual(payload.rows[0].announced_on, date(2024, 5, 11))
        self.assertIsNone(payload.rows[0].free_float_shares)
        self.assertFalse(hasattr(payload.rows[0], "available_at"))

    def test_share_capital_rejects_impossible_component_totals(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceed total_shares"):
            replace(
                self.capital,
                circulating_shares=Decimal(3000000000),
                restricted_shares=Decimal(1000000000),
            )

    def test_corporate_action_preserves_bonus_and_capitalization_separately(self) -> None:
        payload = CorporateActionPayload((self.distribution,))

        row = payload.rows[0]
        self.assertIsNone(row.bonus_shares_per_share)
        self.assertEqual(row.capitalization_shares_per_share, Decimal("0.2"))
        self.assertEqual(row.currency, "CNY")
        self.assertFalse(hasattr(row, "available_at"))

    def test_corporate_action_requires_at_least_one_economic_term(self) -> None:
        with self.assertRaisesRegex(ValueError, "economic term"):
            replace(
                self.distribution,
                cash_per_share=None,
                capitalization_shares_per_share=None,
            )

    def test_rights_ratio_and_subscription_price_are_atomic(self) -> None:
        with self.assertRaisesRegex(ValueError, "rights issue"):
            replace(
                self.distribution,
                cash_per_share=None,
                capitalization_shares_per_share=None,
                rights_shares_per_share=Decimal("0.3"),
                rights_subscription_price=None,
            )

    def test_staging_accepts_xbse_codes_without_changing_listing_identity(self) -> None:
        xbse = replace(
            self.capital,
            code="BJ.430047",
            exchange=Exchange.XBSE,
            provider_record_id="bse:share-capital:430047:2024-05-10",
            source_id="akshare.stock_info_bj_name_code",
        )

        self.assertEqual(ShareCapitalPayload((xbse,)).rows[0].exchange, Exchange.XBSE)

    def test_payloads_reject_duplicate_provider_records_instead_of_overwriting(self) -> None:
        for payload_type, row in (
            (ShareCapitalPayload, self.capital),
            (CorporateActionPayload, self.distribution),
        ):
            with self.subTest(payload_type=payload_type.__name__), self.assertRaisesRegex(
                ValueError, "duplicate provider records"
            ):
                payload_type((row, row))


if __name__ == "__main__":
    unittest.main()
