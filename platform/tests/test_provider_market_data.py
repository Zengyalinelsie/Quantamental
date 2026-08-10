import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.adapters.providers.baostock_market_data import (
    BaostockDailyBarNormalizer,
    ProviderPayloadError,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import Exchange, SpecialTreatment


class BaostockDailyBarNormalizerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = BaostockDailyBarNormalizer()

    def test_normalizes_raw_json_without_claiming_pit(self) -> None:
        observation = self.normalizer.normalize(
            {
                "date": "2018-01-02",
                "open": "12.00",
                "high": "12.40",
                "low": "11.90",
                "close": "12.30",
                "preclose": "12.00",
                "volume": "1000000",
                "amount": "12150000.00",
                "tradestatus": "1",
                "isST": "0",
            },
            listing_id="listing:cmre:xshe",
            exchange=Exchange.XSHE,
            dataset_version_id="dataset:provider-probe:v1",
        )
        self.assertIsNotNone(observation.bar)
        assert observation.bar is not None
        self.assertEqual(observation.bar.close, Decimal("12.30"))
        self.assertEqual(observation.bar.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(observation.state.special_treatment, SpecialTreatment.NONE)
        self.assertIsNone(observation.state.listing_state)

    def test_suspended_blank_row_is_state_not_a_zero_price_bar(self) -> None:
        observation = self.normalizer.normalize(
            {
                "date": "2020-05-28",
                "open": "",
                "high": "",
                "low": "",
                "close": "",
                "preclose": "0.47",
                "volume": "",
                "amount": "",
                "tradestatus": "0",
                "isST": "1",
            },
            listing_id="listing:meidu:xshg",
            exchange=Exchange.XSHG,
            dataset_version_id="dataset:provider-probe:v1",
        )
        self.assertIsNone(observation.bar)
        self.assertFalse(observation.state.is_trading)
        self.assertTrue(observation.state.is_suspended)
        self.assertEqual(observation.state.special_treatment, SpecialTreatment.ST)

    def test_missing_trading_price_fails_instead_of_filling_zero(self) -> None:
        with self.assertRaisesRegex(ProviderPayloadError, "open"):
            self.normalizer.normalize(
                {
                    "date": "2018-01-02",
                    "open": "",
                    "high": "12.40",
                    "low": "11.90",
                    "close": "12.30",
                    "preclose": "12.00",
                    "volume": "1000000",
                    "amount": "12150000.00",
                    "tradestatus": "1",
                    "isST": "0",
                },
                listing_id="listing:cmre:xshe",
                exchange=Exchange.XSHE,
                dataset_version_id="dataset:provider-probe:v1",
            )

    def test_invalid_provider_flags_fail_closed(self) -> None:
        with self.assertRaisesRegex(ProviderPayloadError, "tradestatus"):
            self.normalizer.normalize(
                {"date": date(2018, 1, 2).isoformat(), "tradestatus": "unknown"},
                listing_id="listing:cmre:xshe",
                exchange=Exchange.XSHE,
                dataset_version_id="dataset:provider-probe:v1",
            )


if __name__ == "__main__":
    unittest.main()
