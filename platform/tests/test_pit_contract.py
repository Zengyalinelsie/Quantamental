import unittest
from datetime import UTC, date, datetime, timedelta

from a_share_platform.domain.pit import (
    DataTrustState,
    FactObservation,
    PointInTimeConflictError,
    select_fact_as_of,
)
from a_share_platform.domain.run_context import DataMode


def make_fact(*, trust_state: DataTrustState = DataTrustState.PIT_VERIFIED) -> FactObservation:
    return FactObservation(
        fact_id="fact:revenue:2025",
        security_id="security:CN:600519:XSHG",
        metric_code="revenue",
        value=100.0,
        report_period_end=date(2025, 12, 31),
        announced_at=datetime(2026, 3, 30, 10, tzinfo=UTC),
        available_at=datetime(2026, 3, 30, 10, 1, tzinfo=UTC),
        known_from=datetime(2026, 4, 1, 9, tzinfo=UTC),
        known_to=None,
        revision_sequence=0,
        trust_state=trust_state,
        source_object_id="raw:sha256:abc",
    )


class FactObservationTest(unittest.TestCase):
    def test_strict_history_rejects_fact_before_public_availability(self) -> None:
        fact = make_fact()
        self.assertFalse(
            fact.eligible_for(
                DataMode.STRICT_HISTORICAL,
                decision_time=fact.available_at - timedelta(seconds=1),
                system_time=fact.known_from,
            )
        )

    def test_strict_history_requires_pit_verified_trust(self) -> None:
        fact = make_fact(trust_state=DataTrustState.NORMALIZED_CURRENT)
        self.assertFalse(
            fact.eligible_for(
                DataMode.STRICT_HISTORICAL,
                decision_time=fact.available_at,
                system_time=fact.known_from,
            )
        )
        self.assertTrue(
            fact.eligible_for(
                DataMode.CURRENT_RESEARCH,
                decision_time=fact.available_at,
                system_time=fact.known_from,
            )
        )

    def test_system_time_interval_is_half_open(self) -> None:
        base = make_fact()
        closed = FactObservation(**{**base.__dict__, "known_to": base.known_from + timedelta(days=1)})
        self.assertTrue(closed.visible_in_system(closed.known_to - timedelta(microseconds=1)))
        self.assertFalse(closed.visible_in_system(closed.known_to))

    def test_timezone_free_timestamps_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "announced_at must be timezone-aware"):
            FactObservation(
                **{
                    **make_fact().__dict__,
                    "announced_at": datetime(2026, 3, 30, 10),  # noqa: DTZ001
                }
            )

    def test_public_revision_only_replaces_original_after_its_availability(self) -> None:
        original = make_fact()
        revised = FactObservation(
            **{
                **original.__dict__,
                "fact_id": "fact:revenue:2025:r1",
                "value": 90.0,
                "announced_at": original.announced_at + timedelta(days=30),
                "available_at": original.available_at + timedelta(days=30),
                "revision_sequence": 1,
            }
        )
        before_revision = select_fact_as_of(
            (original, revised),
            DataMode.STRICT_HISTORICAL,
            decision_time=revised.available_at - timedelta(seconds=1),
            system_time=original.known_from,
        )
        after_revision = select_fact_as_of(
            (original, revised),
            DataMode.STRICT_HISTORICAL,
            decision_time=revised.available_at,
            system_time=original.known_from,
        )
        self.assertIs(before_revision, original)
        self.assertIs(after_revision, revised)

    def test_duplicate_visible_revision_fails_closed(self) -> None:
        original = make_fact()
        duplicate = FactObservation(**{**original.__dict__, "fact_id": "fact:duplicate"})
        with self.assertRaises(PointInTimeConflictError):
            select_fact_as_of(
                (original, duplicate),
                DataMode.STRICT_HISTORICAL,
                decision_time=original.available_at,
                system_time=original.known_from,
            )


if __name__ == "__main__":
    unittest.main()
