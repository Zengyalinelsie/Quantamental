from datetime import date
from decimal import Decimal

from a_share_platform.domain.market_data import (
    AdjustmentFactor,
    CalendarDay,
    CorporateAction,
    CorporateActionType,
    DailyBar,
    DailyMarketState,
    ExchangeCalendar,
    MarketDataCatalog,
    PriceAdjustment,
    PriceLimit,
    ShareCapital,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.security_master import Exchange, ListingState, SpecialTreatment


def build_market_data_fixture() -> MarketDataCatalog:
    return MarketDataCatalog(
        bars=(
            DailyBar(
                listing_id="listing:cmre:xshe",
                exchange=Exchange.XSHE,
                session_date=date(2018, 1, 2),
                currency="CNY",
                open=Decimal("12.00"),
                high=Decimal("12.40"),
                low=Decimal("11.90"),
                close=Decimal("12.30"),
                previous_close=Decimal("12.00"),
                volume_shares=1_000_000,
                amount=Decimal("12150000.00"),
                adjustment=PriceAdjustment.UNADJUSTED,
                source_id="contract_fixture",
                dataset_version_id="dataset:p2-contract-fixture:v1",
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            ),
            DailyBar(
                listing_id="listing:meidu:xshg",
                exchange=Exchange.XSHG,
                session_date=date(2020, 5, 22),
                currency="CNY",
                open=Decimal("0.4700"),
                high=Decimal("0.4700"),
                low=Decimal("0.4700"),
                close=Decimal("0.4700"),
                previous_close=Decimal("0.4900"),
                volume_shares=2_485_600,
                amount=Decimal("1168232.0000"),
                adjustment=PriceAdjustment.UNADJUSTED,
                source_id="a_share_mcp_baostock",
                dataset_version_id="dataset:p2-contract-fixture:v1",
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            ),
        ),
        factors=(
            AdjustmentFactor(
                "listing:cmre:xshe",
                date(2018, 1, 2),
                Decimal("0.5"),
                "contract_fixture",
                "dataset:p2-contract-fixture:v1",
                DataTrustState.NORMALIZED_CURRENT,
            ),
        ),
        states=(
            DailyMarketState(
                "listing:cmre:xshe",
                date(2018, 1, 2),
                is_trading=True,
                is_suspended=False,
                source_id="contract_fixture",
                dataset_version_id="dataset:p2-contract-fixture:v1",
                trust_state=DataTrustState.NORMALIZED_CURRENT,
                listing_state=ListingState.ACTIVE,
                special_treatment=SpecialTreatment.NONE,
            ),
            DailyMarketState(
                "listing:meidu:xshg",
                date(2020, 5, 22),
                is_trading=True,
                is_suspended=False,
                source_id="a_share_mcp_baostock",
                dataset_version_id="dataset:p2-contract-fixture:v1",
                trust_state=DataTrustState.NORMALIZED_CURRENT,
                listing_state=ListingState.ACTIVE,
                special_treatment=SpecialTreatment.STAR_ST,
            ),
        ),
        price_limits=(
            PriceLimit(
                "listing:meidu:xshg",
                date(2020, 5, 22),
                Decimal("0.47"),
                Decimal("0.52"),
                "contract_fixture",
            ),
        ),
        share_capital=(
            ShareCapital(
                "listing:cmre:xshe",
                date(2018, 1, 1),
                None,
                total_shares=Decimal(666961416),
                circulating_shares=Decimal(666961416),
                free_float_shares=None,
                source_id="contract_fixture",
                dataset_version_id="dataset:p2-contract-fixture:v1",
            ),
        ),
        corporate_actions=(
            CorporateAction(
                "action:cmre:cash:2018",
                "listing:cmre:xshe",
                CorporateActionType.CASH_DIVIDEND,
                ex_date=date(2018, 6, 1),
                record_date=date(2018, 5, 31),
                cash_per_share=Decimal("0.10"),
                share_ratio=None,
                subscription_price=None,
                currency="CNY",
                source_id="contract_fixture",
            ),
        ),
        calendars=(
            ExchangeCalendar(
                Exchange.XSHE,
                (
                    CalendarDay(Exchange.XSHE, date(2018, 1, 1), False, "new_year", "official"),
                    CalendarDay(Exchange.XSHE, date(2018, 1, 2), True, None, "official"),
                    CalendarDay(Exchange.XSHE, date(2018, 1, 3), True, None, "official"),
                ),
            ),
        ),
    )
