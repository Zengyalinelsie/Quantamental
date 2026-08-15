"""Server-owned desk projection for the prototype Platform Pulse workstation.

The desk answers one question across seven domains: what changed, and can I
trust it.  Those domains belong to different roadmap phases, so this service
resolves each one independently and reports its real state — including "this
capability does not exist yet".  It never fabricates a holding, an event, an
approval or a failure to make the page look complete.

Two rules shape the implementation:

* **Section isolation.**  Every section is resolved in its own ``try`` block.  A
  store that is offline degrades exactly one section; the remaining six keep
  reporting their own truth.  The desk is a situation overview, so a single
  broken domain must not blank the page.
* **Read-only.**  An ordinary refresh only lists existing records.  It never
  ingests, compiles, scores or invokes an agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from a_share_platform.domain.desk import (
    DeskBlocker,
    DeskProjection,
    DeskSection,
    DeskSectionKey,
    DeskSectionStatus,
)
from a_share_platform.ports.system_catalog import SystemCatalogReader

_TITLES = {
    DeskSectionKey.DATA_HEALTH: "数据健康",
    DeskSectionKey.SCREEN_SHIFTS: "最新 Screen 排名变化",
    DeskSectionKey.PORTFOLIO_TRACKING: "组合偏离与风险",
    DeskSectionKey.TIMING_SHADOW: "Timing Shadow",
    DeskSectionKey.EVENT_FEED: "重大事件/公告流",
    DeskSectionKey.PENDING_TASKS: "因子审核与待处理",
    DeskSectionKey.ACTIVE_FAILURES: "运行异常",
}


class ResearchWorkspaceProjector(Protocol):
    def project(self, *, security_query: str | None = None) -> dict[str, Any]: ...


class TimingForecastLister(Protocol):
    def list_forecasts(self) -> tuple[Any, ...]: ...


class FactorReviewLister(Protocol):
    def list_reviews(self) -> tuple[Any, ...]: ...


def _blocker(code: str, reason: str, binding: str) -> DeskBlocker:
    return DeskBlocker(code=code, reason=reason, affected_binding=binding, evidence_ids=())


def _unavailable(key: DeskSectionKey, blocker: DeskBlocker) -> DeskSection:
    return DeskSection(
        key=key,
        status=DeskSectionStatus.UNAVAILABLE,
        title=_TITLES[key],
        blockers=(blocker,),
    )


def _empty(key: DeskSectionKey) -> DeskSection:
    return DeskSection(key=key, status=DeskSectionStatus.EMPTY, title=_TITLES[key])


class DeskProjectionService:
    """Read-only aggregation of the seven desk domains."""

    def __init__(
        self,
        *,
        system_catalog: SystemCatalogReader,
        research_workspace: ResearchWorkspaceProjector,
        timing_repository: TimingForecastLister,
        factor_review_repository: FactorReviewLister,
    ) -> None:
        self._system = system_catalog
        self._workspace = research_workspace
        self._timing = timing_repository
        self._reviews = factor_review_repository

    def project(self, *, now: datetime) -> DeskProjection:
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return DeskProjection(
            sections=(
                self._data_health(),
                self._screen_shifts(),
                self._portfolio_tracking(),
                self._timing_shadow(),
                self._event_feed(),
                self._pending_tasks(),
                self._active_failures(),
            )
        )

    # -- sections backed by a real source ---------------------------------

    def _data_health(self) -> DeskSection:
        key = DeskSectionKey.DATA_HEALTH
        try:
            datasets = tuple(self._system.list_datasets())
            reports = tuple(self._system.list_quality_reports())
        except Exception as error:  # noqa: BLE001 - any store failure degrades one section
            return _unavailable(
                key,
                _blocker(
                    "DATA_HEALTH_CATALOG_UNAVAILABLE",
                    f"数据目录不可读：{error}",
                    "system.catalog",
                ),
            )
        if not datasets:
            return _empty(key)
        covered = {report.dataset_version_id for report in reports}
        failed = tuple(report for report in reports if report.checks_failed)
        coverage = {
            "datasets_total": len(datasets),
            "datasets_with_quality_report": len(covered & {d.dataset_version_id for d in datasets}),
            "quality_reports_total": len(reports),
            "quality_reports_failed": len(failed),
        }
        payload = {
            "datasets_total": coverage["datasets_total"],
            "datasets_with_quality_report": coverage["datasets_with_quality_report"],
            "quality_reports_failed": coverage["quality_reports_failed"],
            "latest_dataset_created_at": max(
                (item.created_at for item in datasets), default=None
            ),
        }
        full = coverage["datasets_with_quality_report"] == coverage["datasets_total"]
        status = (
            DeskSectionStatus.READY
            if full and not failed
            else DeskSectionStatus.PARTIAL
        )
        # Ready needs no coverage gap, but keeping coverage is cheap and auditable.
        return DeskSection(
            key=key,
            status=status,
            title=_TITLES[key],
            coverage=coverage,
            payload=payload,
        )

    def _screen_shifts(self) -> DeskSection:
        key = DeskSectionKey.SCREEN_SHIFTS
        try:
            projection = self._workspace.project()
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                key,
                _blocker(
                    "SCREEN_SHIFT_LEDGER_UNAVAILABLE",
                    f"Screen 投影不可读：{error}",
                    "serving.research_signal_snapshots",
                ),
            )
        screen = projection.get("screen")
        if not screen:
            # The capability exists and the store is reachable; there simply is
            # no qualified SignalSnapshot yet.  That is empty, not unavailable.
            return _empty(key)
        rows = screen.get("rows") if isinstance(screen, dict) else None
        if not rows:
            return _empty(key)
        blockers = tuple(
            _blocker(
                str(item.get("code", "SCREEN_BLOCKER")),
                str(item.get("reason", "")),
                str(item.get("affected_binding", "screen")),
            )
            for item in projection.get("blockers", ())
            if isinstance(item, dict) and str(item.get("reason", "")).strip()
        )
        status = (
            DeskSectionStatus.READY
            if projection.get("status") == "ready"
            else DeskSectionStatus.PARTIAL
        )
        coverage = {"rows_total": len(rows)}
        return DeskSection(
            key=key,
            status=status,
            title=_TITLES[key],
            blockers=blockers,
            coverage=coverage,
            payload={"screen": screen},
        )

    def _timing_shadow(self) -> DeskSection:
        key = DeskSectionKey.TIMING_SHADOW
        try:
            forecasts = tuple(self._timing.list_forecasts())
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                key,
                _blocker(
                    "TIMING_SHADOW_LEDGER_UNAVAILABLE",
                    f"Timing Shadow 账本不可读：{error}",
                    "research.timing_forecasts",
                ),
            )
        if not forecasts:
            return _empty(key)
        latest = max(forecasts, key=lambda item: item.effective_session)
        # Only the passive volatility baseline exists; active timing is P7.
        return DeskSection(
            key=key,
            status=DeskSectionStatus.PARTIAL,
            title=_TITLES[key],
            blockers=(
                _blocker(
                    "P7_ACTIVE_TIMING_NOT_PROMOTED",
                    "主动 Timing 模型尚未晋级，当前只有被动波动率 baseline。",
                    "timing.active_adjustment",
                ),
            ),
            coverage={"forecasts_total": len(forecasts)},
            payload={
                "forecasts_total": len(forecasts),
                "latest_effective_session": latest.effective_session,
                "latest_model_lifecycle": str(latest.model_lifecycle),
                "latest_passive_exposure_ratio": str(latest.passive_exposure_ratio),
            },
        )

    def _pending_tasks(self) -> DeskSection:
        key = DeskSectionKey.PENDING_TASKS
        try:
            reviews = tuple(self._reviews.list_reviews())
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                key,
                _blocker(
                    "PENDING_TASK_REVIEW_STORE_UNAVAILABLE",
                    f"因子审核账本不可读：{error}",
                    "governance.factor_reviews",
                ),
            )
        if not reviews:
            return _empty(key)
        return DeskSection(
            key=key,
            status=DeskSectionStatus.PARTIAL,
            title=_TITLES[key],
            blockers=(
                _blocker(
                    "P9_GENERAL_APPROVAL_QUEUE_NOT_IMPLEMENTED",
                    "当前只覆盖因子晋级审核；通用审批与任务队列属 P9，尚未实现。",
                    "governance.approval_queue",
                ),
            ),
            coverage={"factor_reviews_total": len(reviews)},
            payload={
                "factor_reviews_total": len(reviews),
                "reviews": tuple(
                    {
                        "review_id": item.review_id,
                        "factor_version_id": item.factor_version_id,
                        "decision": str(item.approval.decision),
                        "scope": str(item.approval.scope),
                        "decided_at": item.approval.decided_at,
                    }
                    for item in reviews
                ),
            },
        )

    def _active_failures(self) -> DeskSection:
        key = DeskSectionKey.ACTIVE_FAILURES
        try:
            jobs = tuple(self._system.list_jobs())
        except Exception as error:  # noqa: BLE001
            return _unavailable(
                key,
                _blocker(
                    "ACTIVE_FAILURE_JOB_STORE_UNAVAILABLE",
                    f"作业账本不可读：{error}",
                    "observation.ingestion_jobs",
                ),
            )
        failing = tuple(job for job in jobs if job.failure_reasons or job.status == "failed")
        if not failing:
            return _empty(key)
        return DeskSection(
            key=key,
            status=DeskSectionStatus.PARTIAL,
            title=_TITLES[key],
            blockers=(
                _blocker(
                    "P9_INCIDENT_LEDGER_NOT_IMPLEMENTED",
                    "当前只覆盖摄取作业失败；通用 Incident 账本属 P9，尚未实现。",
                    "observation.incidents",
                ),
            ),
            coverage={"jobs_total": len(jobs), "jobs_failing": len(failing)},
            payload={
                "failures": tuple(
                    {
                        "job_id": job.job_id,
                        "provider_id": job.provider_id,
                        "status": job.status,
                        "failure_reasons": tuple(job.failure_reasons),
                        "updated_at": job.updated_at,
                    }
                    for job in failing
                ),
            },
        )

    # -- sections with no implementation yet -------------------------------

    def _portfolio_tracking(self) -> DeskSection:
        return _unavailable(
            DeskSectionKey.PORTFOLIO_TRACKING,
            _blocker(
                "P6_PORTFOLIO_TRACKING_NOT_IMPLEMENTED",
                "组合构建、偏离与风险能力属 P6，尚未实现；不展示模拟持仓或风险数字。",
                "portfolio.tracking",
            ),
        )

    def _event_feed(self) -> DeskSection:
        return _unavailable(
            DeskSectionKey.EVENT_FEED,
            _blocker(
                "P8_EVENT_FEED_NOT_IMPLEMENTED",
                "事件与公告流能力属 P8，尚未实现；不展示未经证据链验证的事件。",
                "event.feed",
            ),
        )


def desk_section_titles() -> dict[DeskSectionKey, str]:
    return dict(_TITLES)


__all__ = [
    "DeskProjectionService",
    "FactorReviewLister",
    "ResearchWorkspaceProjector",
    "TimingForecastLister",
    "desk_section_titles",
]
