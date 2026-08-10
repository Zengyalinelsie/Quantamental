import unittest
from dataclasses import replace
from datetime import date

from a_share_platform.domain.universe import UniverseConflict, UniverseMembership
from tests.security_master_fixtures import build_security_master_fixture
from tests.universe_fixtures import build_universe_fixture


class UniverseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = build_universe_fixture()
        self.master = build_security_master_fixture()
        self.version_id = "universe-version:core-a-share:v1"

    def test_research_and_tradable_pools_are_separate(self) -> None:
        snapshot = self.catalog.snapshot(self.version_id, date(2020, 5, 22), self.master)
        self.assertIn("listing:meidu:xshg", snapshot.research_listing_ids)
        self.assertNotIn("listing:meidu:xshg", snapshot.tradable_listing_ids)
        meidu = next(row for row in snapshot.rows if row.listing_id == "listing:meidu:xshg")
        self.assertEqual(meidu.exclusion_reasons, ("special_treatment",))
        self.assertEqual(meidu.name, "退市美都")
        self.assertEqual(meidu.delisted_on, date(2020, 8, 14))

    def test_benchmark_membership_and_industry_are_rebuilt_as_of_date(self) -> None:
        snapshot = self.catalog.snapshot(self.version_id, date(2018, 1, 5), self.master)
        benchmark = next(row for row in snapshot.rows if row.listing_id == "listing:spg-a:xshe")
        cmre = next(row for row in snapshot.rows if row.listing_id == "listing:cmre:xshe")
        self.assertTrue(benchmark.benchmark_member)
        self.assertEqual(cmre.industry_name, "房地产业")
        self.assertEqual(cmre.code, "000043")

    def test_delisted_listing_remains_in_historical_snapshot(self) -> None:
        snapshot = self.catalog.snapshot(self.version_id, date(2020, 5, 22), self.master)
        self.assertIn("listing:meidu:xshg", {row.listing_id for row in snapshot.rows})

    def test_universe_diff_reports_additions_and_eligibility_changes(self) -> None:
        added = self.catalog.diff(
            self.version_id,
            date(2018, 1, 5),
            date(2020, 5, 22),
            self.master,
        )
        self.assertEqual(added.added_listing_ids, ("listing:meidu:xshg",))

        changed = self.catalog.diff(
            self.version_id,
            date(2020, 5, 22),
            date(2020, 6, 1),
            self.master,
        )
        self.assertEqual(changed.changed_listing_ids, ("listing:meidu:xshg",))

    def test_coverage_report_is_explicit(self) -> None:
        report = self.catalog.coverage(self.version_id, date(2020, 5, 22), self.master)
        self.assertEqual(report.total_members, 4)
        self.assertEqual(report.identity_resolved, 4)
        self.assertEqual(report.research_eligible, 3)
        self.assertEqual(report.tradable_eligible, 2)
        self.assertEqual(report.identity_coverage, 1.0)

    def test_tradable_membership_cannot_bypass_research_eligibility(self) -> None:
        with self.assertRaisesRegex(ValueError, "tradable eligibility requires research eligibility"):
            UniverseMembership(
                self.version_id,
                "listing:cmre:xshe",
                date(2020, 1, 1),
                None,
                research_eligible=False,
                tradable_eligible=True,
                inclusion_reasons=("listed",),
                exclusion_reasons=(),
                benchmark_member=False,
            )

    def test_overlapping_membership_intervals_fail_closed(self) -> None:
        overlap = replace(
            self.catalog.memberships[0],
            valid_from=date(2019, 1, 1),
        )
        with self.assertRaisesRegex(UniverseConflict, "overlapping membership"):
            replace(self.catalog, memberships=(*self.catalog.memberships, overlap))


if __name__ == "__main__":
    unittest.main()
