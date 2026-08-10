import unittest
from dataclasses import replace
from datetime import date

from a_share_platform.domain.security_master import (
    Board,
    Exchange,
    IdentifierHistory,
    IdentifierKind,
    Listing,
    ListingState,
    SecurityMasterConflict,
    SpecialTreatment,
)
from tests.security_master_fixtures import build_security_master_fixture


class SecurityMasterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.master = build_security_master_fixture()

    def test_code_change_resolves_to_one_listing_and_company(self) -> None:
        before = self.master.resolve_listing(Exchange.XSHE, "000043", date(2018, 1, 5))
        after = self.master.resolve_listing(Exchange.XSHE, "001914", date(2020, 1, 2))
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertEqual(before.listing_id, after.listing_id)
        self.assertEqual(before.company_id, "company:cmre")
        self.assertEqual(before.name, "中航善达")
        self.assertEqual(after.name, "招商积余")

    def test_one_company_can_have_multiple_securities(self) -> None:
        securities = self.master.securities_for_company("company:spg")
        self.assertEqual(
            {security.security_id for security in securities},
            {"security:spg:a", "security:spg:b"},
        )

    def test_st_suspension_and_termination_are_explicit(self) -> None:
        active_st = self.master.snapshot("listing:meidu:xshg", date(2020, 5, 22))
        suspended = self.master.snapshot("listing:meidu:xshg", date(2020, 6, 1))
        terminated = self.master.snapshot("listing:meidu:xshg", date(2020, 8, 14))
        self.assertEqual(active_st.listing_state, ListingState.ACTIVE)
        self.assertEqual(active_st.special_treatment, SpecialTreatment.STAR_ST)
        self.assertEqual(suspended.listing_state, ListingState.SUSPENDED)
        self.assertEqual(terminated.listing_state, ListingState.TERMINATED)

    def test_industry_membership_uses_effective_interval(self) -> None:
        before = self.master.snapshot("listing:cmre:xshe", date(2018, 1, 5))
        after = self.master.snapshot("listing:cmre:xshe", date(2020, 1, 2))
        self.assertEqual(before.industries[0].industry_code, "K70")
        self.assertEqual(after.industries[0].industry_code, "K72")

    def test_overlapping_identifier_history_fails_closed(self) -> None:
        overlapping = IdentifierHistory(
            "listing:cmre:xshe",
            IdentifierKind.CODE,
            "999999",
            date(2019, 1, 1),
            None,
            "contract_fixture",
        )
        with self.assertRaisesRegex(SecurityMasterConflict, "overlapping identifier"):
            replace(self.master, identifiers=(*self.master.identifiers, overlapping))

    def test_exchange_and_board_pair_is_validated(self) -> None:
        valid_pairs = (
            (Exchange.XSHG, Board.MAIN),
            (Exchange.XSHG, Board.STAR),
            (Exchange.XSHE, Board.MAIN),
            (Exchange.XSHE, Board.CHINEXT),
            (Exchange.XBSE, Board.BSE),
        )
        for exchange, board in valid_pairs:
            with self.subTest(exchange=exchange, board=board):
                listing = Listing(
                    f"listing:{exchange.value}:{board.value}",
                    "security:cmre:a",
                    exchange,
                    board,
                    date(2020, 1, 1),
                )
                self.assertEqual((listing.exchange, listing.board), (exchange, board))

        with self.assertRaisesRegex(ValueError, "STAR board requires XSHG"):
            Listing(
                "listing:invalid",
                "security:cmre:a",
                Exchange.XSHE,
                Board.STAR,
                date(2020, 1, 1),
            )


if __name__ == "__main__":
    unittest.main()
