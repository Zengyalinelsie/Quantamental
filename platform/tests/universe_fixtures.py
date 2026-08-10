from datetime import UTC, date, datetime

from a_share_platform.domain.universe import (
    UniverseCatalog,
    UniverseDefinition,
    UniverseMembership,
    UniverseVersion,
)


def build_universe_fixture() -> UniverseCatalog:
    return UniverseCatalog(
        definitions=(
            UniverseDefinition(
                "universe:core-a-share",
                "核心 A 股研究池",
                "ruleset:core-a-share:v1",
                "benchmark:hs300",
            ),
        ),
        versions=(
            UniverseVersion(
                "universe-version:core-a-share:v1",
                "universe:core-a-share",
                "dataset:p2-contract-fixture:v1",
                datetime(2026, 8, 10, 4, 0, tzinfo=UTC),
            ),
        ),
        memberships=(
            UniverseMembership(
                "universe-version:core-a-share:v1",
                "listing:cmre:xshe",
                date(2018, 1, 1),
                None,
                research_eligible=True,
                tradable_eligible=True,
                inclusion_reasons=("a_share", "listed"),
                exclusion_reasons=(),
                benchmark_member=False,
            ),
            UniverseMembership(
                "universe-version:core-a-share:v1",
                "listing:spg-a:xshe",
                date(2018, 1, 1),
                None,
                research_eligible=True,
                tradable_eligible=True,
                inclusion_reasons=("a_share", "listed", "benchmark_member"),
                exclusion_reasons=(),
                benchmark_member=True,
            ),
            UniverseMembership(
                "universe-version:core-a-share:v1",
                "listing:spg-b:xshe",
                date(2018, 1, 1),
                None,
                research_eligible=False,
                tradable_eligible=False,
                inclusion_reasons=(),
                exclusion_reasons=("not_a_share",),
                benchmark_member=False,
            ),
            UniverseMembership(
                "universe-version:core-a-share:v1",
                "listing:meidu:xshg",
                date(2020, 5, 20),
                date(2020, 5, 28),
                research_eligible=True,
                tradable_eligible=False,
                inclusion_reasons=("a_share", "listed"),
                exclusion_reasons=("special_treatment",),
                benchmark_member=False,
            ),
            UniverseMembership(
                "universe-version:core-a-share:v1",
                "listing:meidu:xshg",
                date(2020, 5, 28),
                date(2020, 6, 29),
                research_eligible=True,
                tradable_eligible=False,
                inclusion_reasons=("a_share", "listed"),
                exclusion_reasons=("suspended",),
                benchmark_member=False,
            ),
            UniverseMembership(
                "universe-version:core-a-share:v1",
                "listing:meidu:xshg",
                date(2020, 6, 29),
                date(2020, 8, 14),
                research_eligible=True,
                tradable_eligible=False,
                inclusion_reasons=("a_share", "listed"),
                exclusion_reasons=("pending_delisting",),
                benchmark_member=False,
            ),
        ),
    )
