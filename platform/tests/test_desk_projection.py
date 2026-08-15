"""DeskProjectionService tests.

The desk aggregates seven domains that mature at different phases.  These tests
pin the two properties that make it trustworthy: sections are isolated from each
other's failures, and no section ever invents data it does not have.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any

from a_share_platform.application.desk_projection import DeskProjectionService
from a_share_platform.application.system_catalog import (
    DatasetCatalogEntry,
    IngestionJobEntry,
    QualityReportEntry,
)
from a_share_platform.domain.desk import DeskSectionKey, DeskSectionStatus
from a_share_platform.ports.expected_return import ExpectedReturnLedgerUnavailable
from a_share_platform.ports.factor_reviews import FactorReviewStoreUnavailable
from a_share_platform.ports.signals import SignalSnapshotLedgerUnavailable

NOW = datetime(2026, 8, 15, 1, 35, tzinfo=UTC)


class FakeSystemCatalog:
    """Minimal SystemCatalogReader; raises only what the test asks it to."""

    def __init__(
        self,
        *,
        datasets: tuple[DatasetCatalogEntry, ...] = (),
        quality: tuple[QualityReportEntry, ...] = (),
        jobs: tuple[IngestionJobEntry, ...] = (),
        error: Exception | None = None,
    ) -> None:
        self._datasets = datasets
        self._quality = quality
        self._jobs = jobs
        self._error = error
        self.calls: list[str] = []

    def list_datasets(self) -> tuple[DatasetCatalogEntry, ...]:
        self.calls.append("list_datasets")
        if self._error is not None:
            raise self._error
        return self._datasets

    def list_quality_reports(self) -> tuple[QualityReportEntry, ...]:
        self.calls.append("list_quality_reports")
        if self._error is not None:
            raise self._error
        return self._quality

    def list_lineage(self) -> tuple[Any, ...]:
        self.calls.append("list_lineage")
        return ()

    def list_jobs(self) -> tuple[IngestionJobEntry, ...]:
        self.calls.append("list_jobs")
        if self._error is not None:
            raise self._error
        return self._jobs


class FakeResearchWorkspace:
    def __init__(self, projection: dict[str, Any] | None = None, error: Exception | None = None):
        self._projection = projection or {
            "status": "unavailable",
            "blockers": [],
            "screen": None,
            "investment_view": None,
            "alpha_model": {"status": "unavailable"},
        }
        self._error = error
        self.calls = 0

    def project(self, *, security_query: str | None = None) -> dict[str, Any]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._projection


class FakeTimingRepository:
    def __init__(self, forecasts: tuple[Any, ...] = (), error: Exception | None = None):
        self._forecasts = forecasts
        self._error = error
        self.calls = 0

    def list_forecasts(self) -> tuple[Any, ...]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._forecasts


class FakeFactorReviews:
    def __init__(self, reviews: tuple[Any, ...] = (), error: Exception | None = None):
        self._reviews = reviews
        self._error = error
        self.calls = 0

    def list_reviews(self) -> tuple[Any, ...]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reviews


def dataset(index: int) -> DatasetCatalogEntry:
    return DatasetCatalogEntry(
        dataset_version_id=f"dataset:desk-test:{index}",
        content_hash=f"{index:064d}",
        created_at=NOW,
        schema_version="1",
    )


def quality(dataset_version_id: str, *, failed: int = 0) -> QualityReportEntry:
    return QualityReportEntry(
        quality_report_id=f"quality:{dataset_version_id}",
        dataset_version_id=dataset_version_id,
        job_id="job:desk-test",
        status="failed" if failed else "passed",
        checks_passed=3,
        checks_failed=failed,
        issue_counts={},
        warnings=(),
        created_at=NOW,
    )


def job(*, status: str = "succeeded", failures: tuple[str, ...] = ()) -> IngestionJobEntry:
    return IngestionJobEntry(
        job_id="job:desk-test",
        plan_id="plan:desk-test",
        provider_id="provider:desk-test",
        status=status,
        output_trust_state="normalized_current",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 15),
        created_at=NOW,
        updated_at=NOW,
        dataset_version_id="dataset:desk-test:1",
        failure_reasons=failures,
        checkpoints=(),
        quality_reports=(),
        coverage_reports=(),
    )


def service(
    *,
    system: FakeSystemCatalog | None = None,
    workspace: FakeResearchWorkspace | None = None,
    timing: FakeTimingRepository | None = None,
    reviews: FakeFactorReviews | None = None,
) -> DeskProjectionService:
    return DeskProjectionService(
        system_catalog=system or FakeSystemCatalog(),
        research_workspace=workspace or FakeResearchWorkspace(),
        timing_repository=timing or FakeTimingRepository(),
        factor_review_repository=reviews or FakeFactorReviews(),
    )


class DeskProjectionShapeTest(unittest.TestCase):
    def test_projection_always_returns_all_seven_sections(self) -> None:
        projection = service().project(now=NOW)
        self.assertEqual(len(projection.sections), 7)

    def test_unimplemented_domains_declare_their_phase(self) -> None:
        """Portfolio tracking is P6 and the event feed is P8; neither is faked."""
        projection = service().project(now=NOW)
        portfolio = projection.section(DeskSectionKey.PORTFOLIO_TRACKING)
        events = projection.section(DeskSectionKey.EVENT_FEED)
        self.assertEqual(portfolio.status, DeskSectionStatus.UNAVAILABLE)
        self.assertEqual(events.status, DeskSectionStatus.UNAVAILABLE)
        self.assertEqual(
            portfolio.blockers[0].code, "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED"
        )
        self.assertEqual(events.blockers[0].code, "P8_EVENT_FEED_NOT_IMPLEMENTED")
        self.assertIsNone(portfolio.payload)
        self.assertIsNone(events.payload)

    def test_no_section_carries_prototype_sample_values(self) -> None:
        """Figma DESIGN FIXTURE numbers must never reach a projection."""
        projection = service().project(now=NOW)
        rendered = repr(projection)
        for fixture in ("94.2", "貴州", "贵州茅台", "600519", "3.2", "28.1", "-1.62", "35 标的"):
            self.assertNotIn(fixture, rendered)


class DeskSectionIsolationTest(unittest.TestCase):
    """One broken domain must not blank the other six."""

    def test_catalog_failure_isolates_to_its_own_sections(self) -> None:
        system = FakeSystemCatalog(error=RuntimeError("catalog store offline"))
        projection = service(system=system).project(now=NOW)
        health = projection.section(DeskSectionKey.DATA_HEALTH)
        failures = projection.section(DeskSectionKey.ACTIVE_FAILURES)
        self.assertEqual(health.status, DeskSectionStatus.UNAVAILABLE)
        self.assertEqual(failures.status, DeskSectionStatus.UNAVAILABLE)
        # Sections fed by other sources are untouched.
        self.assertEqual(len(projection.sections), 7)
        screen = projection.section(DeskSectionKey.SCREEN_SHIFTS)
        self.assertNotEqual(screen.blockers, health.blockers)

    def test_workspace_failure_isolates_to_screen_shifts(self) -> None:
        workspace = FakeResearchWorkspace(
            error=ExpectedReturnLedgerUnavailable("investment view store offline")
        )
        system = FakeSystemCatalog(datasets=(dataset(1),), quality=(quality("dataset:desk-test:1"),))
        projection = service(system=system, workspace=workspace).project(now=NOW)
        screen = projection.section(DeskSectionKey.SCREEN_SHIFTS)
        self.assertEqual(screen.status, DeskSectionStatus.UNAVAILABLE)
        self.assertIn("offline", screen.blockers[0].reason)
        # Data health still reports its own real state.
        self.assertNotEqual(
            projection.section(DeskSectionKey.DATA_HEALTH).status,
            DeskSectionStatus.UNAVAILABLE,
        )

    def test_signal_ledger_failure_is_reported_not_raised(self) -> None:
        workspace = FakeResearchWorkspace(
            error=SignalSnapshotLedgerUnavailable("signal snapshot store offline")
        )
        projection = service(workspace=workspace).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.SCREEN_SHIFTS).status,
            DeskSectionStatus.UNAVAILABLE,
        )

    def test_timing_failure_isolates_to_timing_shadow(self) -> None:
        timing = FakeTimingRepository(error=RuntimeError("timing ledger offline"))
        projection = service(timing=timing).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.TIMING_SHADOW).status,
            DeskSectionStatus.UNAVAILABLE,
        )
        self.assertEqual(len(projection.sections), 7)

    def test_review_failure_isolates_to_pending_tasks(self) -> None:
        reviews = FakeFactorReviews(error=FactorReviewStoreUnavailable("review store offline"))
        projection = service(reviews=reviews).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.PENDING_TASKS).status,
            DeskSectionStatus.UNAVAILABLE,
        )

    def test_every_source_failing_still_yields_seven_sections(self) -> None:
        projection = service(
            system=FakeSystemCatalog(error=RuntimeError("a")),
            workspace=FakeResearchWorkspace(error=ExpectedReturnLedgerUnavailable("b")),
            timing=FakeTimingRepository(error=RuntimeError("c")),
            reviews=FakeFactorReviews(error=FactorReviewStoreUnavailable("d")),
        ).project(now=NOW)
        self.assertEqual(len(projection.sections), 7)
        for section in projection.sections:
            self.assertEqual(section.status, DeskSectionStatus.UNAVAILABLE)
            self.assertTrue(section.blockers, f"{section.key} must explain itself")


class DeskEmptyVersusUnavailableTest(unittest.TestCase):
    """Waiting on data and waiting on implementation are different answers."""

    def test_reachable_but_recordless_screen_is_empty_not_unavailable(self) -> None:
        workspace = FakeResearchWorkspace({
            "status": "unavailable",
            "blockers": [],
            "screen": None,
            "investment_view": None,
            "alpha_model": {"status": "unavailable"},
        })
        projection = service(workspace=workspace).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.SCREEN_SHIFTS).status,
            DeskSectionStatus.EMPTY,
        )

    def test_store_unavailable_blocker_is_not_reported_as_empty(self) -> None:
        """The workspace reports its own store failures as blockers, not raises.

        Without inspecting them the desk would call an unreachable ledger
        "empty", telling the operator to wait for data when the real problem is
        that no store is configured.
        """
        workspace = FakeResearchWorkspace({
            "status": "unavailable",
            "blockers": [
                {
                    "code": "signal_snapshot_store_unavailable",
                    "reason": "ASP_DATABASE_URL is not configured for SignalSnapshot persistence",
                    "affected_binding": "serving.research_signal_snapshots",
                    "evidence_ids": [],
                },
            ],
            "screen": None,
            "investment_view": None,
            "alpha_model": {"status": "unavailable"},
        })
        projection = service(workspace=workspace).project(now=NOW)
        section = projection.section(DeskSectionKey.SCREEN_SHIFTS)
        self.assertEqual(section.status, DeskSectionStatus.UNAVAILABLE)
        self.assertEqual(section.blockers[0].code, "signal_snapshot_store_unavailable")

    def test_non_store_blocker_still_reads_as_empty(self) -> None:
        """A reachable ledger with no qualified snapshot is empty, not broken."""
        workspace = FakeResearchWorkspace({
            "status": "unavailable",
            "blockers": [
                {
                    "code": "research_signal_snapshot_unavailable",
                    "reason": "没有 research_backtest scope 的 SignalSnapshot。",
                    "affected_binding": "approval_scope:research_backtest",
                    "evidence_ids": [],
                },
            ],
            "screen": None,
            "investment_view": None,
            "alpha_model": {"status": "unavailable"},
        })
        projection = service(workspace=workspace).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.SCREEN_SHIFTS).status,
            DeskSectionStatus.EMPTY,
        )

    def test_reachable_but_recordless_timing_is_empty(self) -> None:
        projection = service(timing=FakeTimingRepository(forecasts=())).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.TIMING_SHADOW).status,
            DeskSectionStatus.EMPTY,
        )

    def test_reachable_but_recordless_reviews_is_empty(self) -> None:
        projection = service(reviews=FakeFactorReviews(reviews=())).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.PENDING_TASKS).status,
            DeskSectionStatus.EMPTY,
        )

    def test_no_datasets_makes_data_health_empty(self) -> None:
        projection = service(system=FakeSystemCatalog(datasets=())).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.DATA_HEALTH).status,
            DeskSectionStatus.EMPTY,
        )


class DeskCoverageTest(unittest.TestCase):
    def test_partial_data_health_declares_its_coverage_gap(self) -> None:
        system = FakeSystemCatalog(
            datasets=(dataset(1), dataset(2), dataset(3)),
            quality=(quality("dataset:desk-test:1"),),
        )
        projection = service(system=system).project(now=NOW)
        health = projection.section(DeskSectionKey.DATA_HEALTH)
        self.assertEqual(health.status, DeskSectionStatus.PARTIAL)
        self.assertEqual(health.coverage["datasets_total"], 3)
        self.assertEqual(health.coverage["datasets_with_quality_report"], 1)

    def test_every_partial_section_declares_coverage_or_blocker(self) -> None:
        system = FakeSystemCatalog(
            datasets=(dataset(1), dataset(2)),
            quality=(quality("dataset:desk-test:1"),),
            jobs=(job(status="failed", failures=("provider timeout",)),),
        )
        projection = service(system=system).project(now=NOW)
        for section in projection.sections:
            if section.status is DeskSectionStatus.PARTIAL:
                self.assertTrue(
                    section.coverage or section.blockers,
                    f"{section.key} is partial without declaring the gap",
                )

    def test_pending_tasks_partial_scope_is_declared(self) -> None:
        """Only factor promotion review exists; the general queue is P9."""
        system = FakeSystemCatalog(datasets=(dataset(1),), quality=(quality("dataset:desk-test:1"),))
        projection = service(system=system).project(now=NOW)
        pending = projection.section(DeskSectionKey.PENDING_TASKS)
        self.assertIn(
            pending.status,
            (DeskSectionStatus.EMPTY, DeskSectionStatus.PARTIAL),
        )


class DeskReadPathTest(unittest.TestCase):
    def test_projection_only_reads_and_never_computes(self) -> None:
        """An ordinary refresh must not trigger ingestion, compilation or agents."""
        system = FakeSystemCatalog()
        workspace = FakeResearchWorkspace()
        timing = FakeTimingRepository()
        reviews = FakeFactorReviews()
        service(
            system=system, workspace=workspace, timing=timing, reviews=reviews
        ).project(now=NOW)
        self.assertLessEqual(workspace.calls, 1)
        self.assertLessEqual(timing.calls, 1)
        self.assertLessEqual(reviews.calls, 1)
        for call in system.calls:
            self.assertTrue(call.startswith("list_"), f"{call} is not a read")

    def test_active_failures_reports_real_job_failures(self) -> None:
        system = FakeSystemCatalog(
            datasets=(dataset(1),),
            quality=(quality("dataset:desk-test:1"),),
            jobs=(job(status="failed", failures=("provider rate limited",)),),
        )
        projection = service(system=system).project(now=NOW)
        failures = projection.section(DeskSectionKey.ACTIVE_FAILURES)
        self.assertEqual(failures.status, DeskSectionStatus.PARTIAL)
        self.assertIn("provider rate limited", repr(failures.payload))

    def test_no_failed_jobs_makes_active_failures_empty(self) -> None:
        system = FakeSystemCatalog(
            datasets=(dataset(1),),
            quality=(quality("dataset:desk-test:1"),),
            jobs=(job(status="succeeded"),),
        )
        projection = service(system=system).project(now=NOW)
        self.assertEqual(
            projection.section(DeskSectionKey.ACTIVE_FAILURES).status,
            DeskSectionStatus.EMPTY,
        )


if __name__ == "__main__":
    unittest.main()
