"""Desk section contract tests.

The desk is the first consumer of the section contract that PUI-02–PUI-09 will
reuse, so these tests pin the invariants rather than the desk's current wording.
"""

from __future__ import annotations

import unittest

from a_share_platform.domain.desk import (
    DeskBlocker,
    DeskProjection,
    DeskSection,
    DeskSectionKey,
    DeskSectionStatus,
)


def blocker(code: str = "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED") -> DeskBlocker:
    return DeskBlocker(
        code=code,
        reason="组合跟踪能力属 P6，尚未实现。",
        affected_binding="portfolio.tracking",
        evidence_ids=(),
    )


def section(
    key: DeskSectionKey = DeskSectionKey.DATA_HEALTH,
    status: DeskSectionStatus = DeskSectionStatus.UNAVAILABLE,
    *,
    title: str = "数据健康",
    blockers: tuple[DeskBlocker, ...] = (),
    coverage: dict[str, object] | None = None,
    payload: object | None = None,
) -> DeskSection:
    return DeskSection(
        key=key,
        status=status,
        title=title,
        blockers=blockers,
        coverage=dict(coverage or {}),
        payload=payload,
    )


ALL_KEYS = (
    DeskSectionKey.DATA_HEALTH,
    DeskSectionKey.SCREEN_SHIFTS,
    DeskSectionKey.PORTFOLIO_TRACKING,
    DeskSectionKey.TIMING_SHADOW,
    DeskSectionKey.EVENT_FEED,
    DeskSectionKey.PENDING_TASKS,
    DeskSectionKey.ACTIVE_FAILURES,
)


class DeskSectionContractTest(unittest.TestCase):
    def test_partial_requires_coverage_or_blocker(self) -> None:
        """A bare "partial" label carries no information, so it is rejected."""
        with self.assertRaises(ValueError) as error:
            section(status=DeskSectionStatus.PARTIAL, payload={"metrics": ()})
        self.assertIn("partial", str(error.exception))

    def test_partial_accepts_coverage(self) -> None:
        value = section(
            status=DeskSectionStatus.PARTIAL,
            coverage={"datasets_total": 3, "datasets_with_quality_report": 1},
            payload={"metrics": ()},
        )
        self.assertEqual(value.status, DeskSectionStatus.PARTIAL)

    def test_partial_accepts_blocker(self) -> None:
        value = section(
            status=DeskSectionStatus.PARTIAL,
            blockers=(blocker("PENDING_TASK_SCOPE_LIMITED"),),
            payload={"metrics": ()},
        )
        self.assertEqual(value.status, DeskSectionStatus.PARTIAL)

    def test_unavailable_requires_a_blocker(self) -> None:
        """Unavailable without a reason is indistinguishable from a bug."""
        with self.assertRaises(ValueError) as error:
            section(status=DeskSectionStatus.UNAVAILABLE)
        self.assertIn("unavailable", str(error.exception))

    def test_unavailable_rejects_payload(self) -> None:
        with self.assertRaises(ValueError):
            section(
                status=DeskSectionStatus.UNAVAILABLE,
                blockers=(blocker(),),
                payload={"metrics": ()},
            )

    def test_empty_rejects_payload(self) -> None:
        with self.assertRaises(ValueError):
            section(status=DeskSectionStatus.EMPTY, payload={"metrics": ()})

    def test_empty_needs_no_blocker(self) -> None:
        """Empty means the capability works and holds no record yet."""
        value = section(status=DeskSectionStatus.EMPTY)
        self.assertEqual(value.status, DeskSectionStatus.EMPTY)
        self.assertEqual(value.blockers, ())

    def test_ready_requires_payload(self) -> None:
        with self.assertRaises(ValueError):
            section(status=DeskSectionStatus.READY)

    def test_title_must_not_be_empty(self) -> None:
        with self.assertRaises(ValueError):
            section(status=DeskSectionStatus.EMPTY, title="  ")

    def test_blocker_requires_code_and_reason(self) -> None:
        with self.assertRaises(ValueError):
            DeskBlocker(code="", reason="x", affected_binding="y", evidence_ids=())
        with self.assertRaises(ValueError):
            DeskBlocker(code="X", reason="  ", affected_binding="y", evidence_ids=())

    def test_coverage_is_copied_so_callers_cannot_mutate_a_frozen_section(self) -> None:
        coverage = {"datasets_total": 3}
        value = section(
            status=DeskSectionStatus.PARTIAL,
            coverage=coverage,
            payload={"metrics": ()},
        )
        coverage["datasets_total"] = 999
        self.assertEqual(value.coverage["datasets_total"], 3)


class DeskProjectionContractTest(unittest.TestCase):
    def _sections(self) -> tuple[DeskSection, ...]:
        return tuple(
            section(key=key, status=DeskSectionStatus.EMPTY, title=f"section-{key.value}")
            for key in ALL_KEYS
        )

    def test_projection_holds_all_seven_sections(self) -> None:
        value = DeskProjection(sections=self._sections())
        self.assertEqual(len(value.sections), 7)
        self.assertEqual(tuple(item.key for item in value.sections), ALL_KEYS)

    def test_projection_rejects_a_missing_section(self) -> None:
        """The desk skeleton stays stable; sections never disappear."""
        incomplete = self._sections()[:-1]
        with self.assertRaises(ValueError) as error:
            DeskProjection(sections=incomplete)
        self.assertIn("seven", str(error.exception).lower())

    def test_projection_rejects_duplicate_sections(self) -> None:
        duplicated = self._sections()[:-1] + (self._sections()[0],)
        with self.assertRaises(ValueError):
            DeskProjection(sections=duplicated)

    def test_projection_orders_sections_by_the_prototype_layout(self) -> None:
        shuffled = tuple(reversed(self._sections()))
        value = DeskProjection(sections=shuffled)
        self.assertEqual(tuple(item.key for item in value.sections), ALL_KEYS)

    def test_section_lookup_by_key(self) -> None:
        value = DeskProjection(sections=self._sections())
        found = value.section(DeskSectionKey.EVENT_FEED)
        self.assertEqual(found.key, DeskSectionKey.EVENT_FEED)


if __name__ == "__main__":
    unittest.main()
