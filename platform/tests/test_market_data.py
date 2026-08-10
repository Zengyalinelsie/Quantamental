import unittest
from dataclasses import replace
from datetime import date
from decimal import Decimal

from a_share_platform.domain.market_data import (
    CorporateAction,
    CorporateActionType,
    MarketDataConflict,
    MarketDataUnavailable,
    PriceAdjustment,
    PriceLimitStatus,
)
from a_share_platform.domain.security_master import ListingState, SpecialTreatment
from tests.market_data_fixtures import build_market_data_fixture


class MarketDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_market_data_fixture()

    def test_daily_bar_is_raw_and_has_explicit_units(self) -> None:
        bar = self.catalog.select_bar("listing:meidu:xshg", date(2020, 5, 22))
        self.assertEqual(bar.adjustment, PriceAdjustment.UNADJUSTED)
        self.assertEqual(bar.currency, "CNY")
        self.assertEqual(bar.volume_shares, 2_485_600)
        self.assertEqual(bar.amount, Decimal("1168232.0000"))

    def test_invalid_ohlc_relationship_fails_closed(self) -> None:
        bar = self.catalog.bars[0]
        with self.assertRaisesRegex(ValueError, "high must be at least"):
            replace(bar, high=Decimal("11.00"))

    def test_adjusted_close_requires_independent_factor(self) -> None:
        self.assertEqual(
            self.catalog.adjusted_close("listing:cmre:xshe", date(2018, 1, 2)),
            Decimal("6.150"),
        )
        with self.assertRaisesRegex(MarketDataUnavailable, "adjustment factor"):
            self.catalog.adjusted_close("listing:meidu:xshg", date(2020, 5, 22))

    def test_price_limit_status_uses_explicit_bounds(self) -> None:
        self.assertEqual(
            self.catalog.price_limit_status("listing:meidu:xshg", date(2020, 5, 22)),
            PriceLimitStatus.LOCKED_DOWN,
        )

    def test_daily_state_keeps_trading_listing_and_st_status_separate(self) -> None:
        state = next(
            item
            for item in self.catalog.states
            if item.listing_id == "listing:meidu:xshg"
        )
        self.assertTrue(state.is_trading)
        self.assertFalse(state.is_suspended)
        self.assertEqual(state.listing_state, ListingState.ACTIVE)
        self.assertEqual(state.special_treatment, SpecialTreatment.STAR_ST)

    def test_share_capital_and_market_cap_do_not_fill_missing_free_float(self) -> None:
        capital = self.catalog.share_capital_at("listing:cmre:xshe", date(2018, 1, 2))
        self.assertIsNone(capital.free_float_shares)
        self.assertEqual(
            self.catalog.market_cap("listing:cmre:xshe", date(2018, 1, 2)),
            Decimal("12.30") * Decimal(666961416),
        )

    def test_calendar_returns_next_known_trading_session(self) -> None:
        calendar = self.catalog.calendar("XSHE")
        self.assertFalse(calendar.is_session(date(2018, 1, 1)))
        self.assertEqual(calendar.next_session(date(2018, 1, 1)), date(2018, 1, 2))
        self.assertEqual(calendar.next_session(date(2018, 1, 2)), date(2018, 1, 3))

    def test_all_corporate_action_types_require_their_economic_terms(self) -> None:
        for action_type in (
            CorporateActionType.BONUS_SHARE,
            CorporateActionType.SPLIT,
            CorporateActionType.REVERSE_SPLIT,
        ):
            with self.subTest(action_type=action_type):
                action = CorporateAction(
                    f"action:{action_type.value}",
                    "listing:cmre:xshe",
                    action_type,
                    date(2020, 1, 2),
                    date(2020, 1, 1),
                    cash_per_share=None,
                    share_ratio=Decimal("0.5"),
                    subscription_price=None,
                    currency="CNY",
                    source_id="contract_fixture",
                )
                self.assertEqual(action.share_ratio, Decimal("0.5"))

        rights = CorporateAction(
            "action:rights",
            "listing:cmre:xshe",
            CorporateActionType.RIGHTS_ISSUE,
            date(2020, 1, 2),
            date(2020, 1, 1),
            cash_per_share=None,
            share_ratio=Decimal("0.3"),
            subscription_price=Decimal("8.00"),
            currency="CNY",
            source_id="contract_fixture",
        )
        self.assertEqual(rights.subscription_price, Decimal("8.00"))

    def test_conflicting_provider_observations_are_retained_and_block_selection(self) -> None:
        conflicting = replace(
            self.catalog.bars[0],
            close=Decimal("12.31"),
            source_id="akshare",
        )
        catalog = replace(self.catalog, bars=(*self.catalog.bars, conflicting))
        self.assertEqual(
            len(catalog.bars_for("listing:cmre:xshe", date(2018, 1, 2))),
            2,
        )
        with self.assertRaisesRegex(MarketDataConflict, "conflicting daily bars"):
            catalog.select_bar("listing:cmre:xshe", date(2018, 1, 2))
        issue = next(item for item in catalog.quality_report().issues if item.code == "bar_conflict")
        self.assertEqual(issue.listing_id, "listing:cmre:xshe")


if __name__ == "__main__":
    unittest.main()
