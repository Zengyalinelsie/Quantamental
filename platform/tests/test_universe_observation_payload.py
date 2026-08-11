import unittest
from datetime import date

from a_share_platform.adapters.providers.backfill_payloads import (
    StagedUniverseMembership,
    UniverseMembershipPayload,
)
from a_share_platform.domain.backfill import UniverseObservationMode


class UniverseObservationPayloadTest(unittest.TestCase):
    def test_discrete_snapshot_requires_one_day_rows_and_explicit_gaps(self) -> None:
        payload = UniverseMembershipPayload(
            benchmark_code="000300",
            rows=(
                StagedUniverseMembership(
                    code="SH.600519",
                    valid_from=date(2018, 1, 31),
                    valid_to=date(2018, 2, 1),
                    source_id="baostock_sdk.query_hs300_stocks:month_end_discrete",
                ),
            ),
            observation_mode=UniverseObservationMode.DISCRETE_MONTH_END,
            observed_dates=(date(2018, 1, 31),),
            unobserved_intervals=(
                (date(2018, 1, 1), date(2018, 1, 31)),
                (date(2018, 2, 1), date(2018, 3, 1)),
            ),
        )

        self.assertEqual(
            payload.observation_mode,
            UniverseObservationMode.DISCRETE_MONTH_END,
        )
        self.assertEqual(payload.observed_dates, (date(2018, 1, 31),))

    def test_discrete_snapshot_rejects_inferred_continuity(self) -> None:
        with self.assertRaisesRegex(ValueError, "one-day"):
            UniverseMembershipPayload(
                benchmark_code="000300",
                rows=(
                    StagedUniverseMembership(
                        code="SH.600519",
                        valid_from=date(2018, 1, 31),
                        valid_to=date(2018, 2, 28),
                        source_id="baostock_sdk.query_hs300_stocks:month_end_discrete",
                    ),
                ),
                observation_mode=UniverseObservationMode.DISCRETE_MONTH_END,
                observed_dates=(date(2018, 1, 31),),
                unobserved_intervals=((date(2018, 2, 1), date(2018, 2, 28)),),
            )

    def test_unobserved_intervals_must_not_cover_an_observed_date(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap an observed date"):
            UniverseMembershipPayload(
                benchmark_code="000300",
                rows=(
                    StagedUniverseMembership(
                        code="SH.600519",
                        valid_from=date(2018, 1, 31),
                        valid_to=date(2018, 2, 1),
                        source_id="baostock_sdk.query_hs300_stocks:month_end_discrete",
                    ),
                ),
                observation_mode=UniverseObservationMode.DISCRETE_MONTH_END,
                observed_dates=(date(2018, 1, 31),),
                unobserved_intervals=((date(2018, 1, 1), date(2018, 2, 1)),),
            )


if __name__ == "__main__":
    unittest.main()
