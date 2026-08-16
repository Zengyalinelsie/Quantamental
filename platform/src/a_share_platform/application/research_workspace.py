"""Server-owned P5 research workspace projections.

The projection layer formats and ranks frozen domain records for the UI.  It
never compiles a signal, fills an unavailable value with zero, or exposes a
forward-approved snapshot through the research surface.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from a_share_platform.application.signal_snapshots import (
    ResearchSignalSnapshotQueryService,
)
from a_share_platform.domain.factor_reviews import FactorPromotionReview
from a_share_platform.domain.investment_view import (
    InvestmentComponent,
    InvestmentComponentStatus,
    InvestmentView,
)
from a_share_platform.domain.security_master import SecurityIdentitySnapshot, SecurityMaster
from a_share_platform.domain.signals import SignalSnapshot
from a_share_platform.ports.expected_return import (
    ExpectedReturnLedgerRepository,
    ExpectedReturnLedgerUnavailable,
)
from a_share_platform.ports.factor_reviews import (
    FactorReviewRepository,
    FactorReviewStoreUnavailable,
)
from a_share_platform.ports.signals import (
    SignalSnapshotLedgerUnavailable,
    SignalSnapshotRepository,
)

Projection = dict[str, Any]

_COMPONENT_LABELS = {
    "quality": "公司质量",
    "valuation": "估值预期差",
    "revision": "基本面改善",
    "event": "事件调整",
}


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _percent(value: Decimal) -> Projection:
    return {
        "raw": _decimal_text(value),
        "display": f"{value * Decimal(100):+.2f}%",
    }


def _score(value: Decimal) -> Projection:
    return {"raw": _decimal_text(value), "display": f"{value:.3f}"}


def _confidence(value: Decimal) -> Projection:
    return {"raw": _decimal_text(value), "display": f"{value:.2f}"}


def _time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _content_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(encoded).hexdigest()}"


def _blocker(code: str, reason: str, affected_binding: str) -> Projection:
    return {
        "code": code,
        "reason": reason,
        "affected_binding": affected_binding,
        "evidence_ids": [],
    }


class ResearchWorkspaceProjectionService:
    """Read-only projection over immutable P5 research ledgers."""

    def __init__(
        self,
        *,
        expected_return_repository: ExpectedReturnLedgerRepository,
        signal_snapshot_repository: SignalSnapshotRepository,
        factor_review_repository: FactorReviewRepository,
        security_master: SecurityMaster,
    ) -> None:
        if not isinstance(security_master, SecurityMaster):
            raise TypeError("security_master must be a SecurityMaster")
        self._expected_returns = expected_return_repository
        self._signals = ResearchSignalSnapshotQueryService(signal_snapshot_repository)
        self._factor_reviews = factor_review_repository
        self._security_master = security_master

    def project(self, *, security_query: str | None = None) -> Projection:
        query = None if security_query is None else security_query.strip()
        query = query or None
        blockers: list[Projection] = []
        try:
            views = self._expected_returns.list_views()
        except ExpectedReturnLedgerUnavailable as error:
            views = ()
            blockers.append(
                _blocker(
                    "investment_view_store_unavailable",
                    str(error),
                    "research.investment_views",
                )
            )
        try:
            snapshots = self._signals.list_snapshots()
        except SignalSnapshotLedgerUnavailable as error:
            snapshots = ()
            blockers.append(
                _blocker(
                    "signal_snapshot_store_unavailable",
                    str(error),
                    "serving.research_signal_snapshots",
                )
            )

        selected_snapshots = self._latest_screen_snapshots(snapshots)
        selected_security_id = self._select_security_id(selected_snapshots, query)
        selected_snapshot = next(
            (value for value in selected_snapshots if value.security_id == selected_security_id),
            None,
        )
        selected_view = self._select_view(
            views,
            query=query,
            preferred_security_id=selected_security_id,
            preferred_view_id=(
                None if selected_snapshot is None else selected_snapshot.investment_view_id
            ),
            preferred_view_hash=(
                None if selected_snapshot is None else selected_snapshot.investment_view_hash
            ),
        )
        if selected_view is None:
            blockers.append(
                _blocker(
                    "investment_view_unavailable",
                    "没有符合当前筛选条件的冻结 InvestmentView；系统不会生成演示收益。",
                    query or "latest_research_investment_view",
                )
            )
        if not selected_snapshots:
            blockers.append(
                _blocker(
                    "research_signal_snapshot_unavailable",
                    "没有 research_backtest scope 的 SignalSnapshot；forward scope 不会泄漏到研究接口。",
                    "approval_scope:research_backtest",
                )
            )

        alpha = self._project_alpha(
            selected_snapshots,
            views,
            selected_security_id=selected_security_id,
        )
        if alpha["status"] == "unavailable":
            blockers.append(
                _blocker(
                    "approved_alpha_model_unavailable",
                    "当前没有证据完整且对 research_backtest 获批的 Alpha Model。",
                    "approval_scope:research_backtest",
                )
            )

        screen = (
            None
            if not selected_snapshots
            else self._project_screen(
                selected_snapshots,
                selected_security_id=selected_security_id,
                views=views,
            )
        )
        investment_view = (
            None if selected_view is None else self._project_investment_view(selected_view)
        )
        ready_parts = sum(
            (screen is not None, investment_view is not None, alpha["status"] == "ready")
        )
        status = "ready" if ready_parts == 3 else "partial" if ready_parts else "unavailable"
        return {
            "status": status,
            "blockers": blockers,
            "screen": screen,
            "investment_view": investment_view,
            "alpha_model": alpha,
        }

    @staticmethod
    def _latest_screen_snapshots(
        values: tuple[SignalSnapshot, ...],
    ) -> tuple[SignalSnapshot, ...]:
        if not values:
            return ()
        latest = max(
            values,
            key=lambda value: (value.decision_time, value.created_at, value.snapshot_id),
        )
        selected = tuple(
            value
            for value in values
            if ResearchWorkspaceProjectionService._screen_binding(value)
            == ResearchWorkspaceProjectionService._screen_binding(latest)
        )
        return tuple(sorted(selected, key=lambda value: (value.rank, value.security_id)))

    @staticmethod
    def _screen_binding(value: SignalSnapshot) -> tuple[object, ...]:
        """Return fields that must be identical within one frozen Screen."""

        return (
            value.decision_time,
            value.universe_version_id,
            value.horizon_trading_days,
            value.model_version_id,
            value.factor_version_ids,
            value.factor_version_hashes,
            value.factor_review_ids,
            value.factor_review_hashes,
            value.dataset_version_ids,
            value.feature_version_ids,
            value.approval_scope,
            value.run_context.data_mode,
            value.run_context.deployment_stage,
            value.trust_state,
        )

    def _select_security_id(
        self,
        snapshots: tuple[SignalSnapshot, ...],
        query: str | None,
    ) -> str | None:
        if not snapshots:
            return None
        if query is None:
            return snapshots[0].security_id
        normalized = query.casefold()
        for value in snapshots:
            identity = self._identity(value.security_id, value.decision_time)
            if normalized in {
                value.security_id.casefold(),
                str(identity["symbol"]).casefold(),
                str(identity["display_name"]).casefold(),
            }:
                return value.security_id
        return None

    def _select_view(
        self,
        views: tuple[InvestmentView, ...],
        *,
        query: str | None,
        preferred_security_id: str | None,
        preferred_view_id: str | None,
        preferred_view_hash: str | None,
    ) -> InvestmentView | None:
        if preferred_view_id is not None:
            return next(
                (
                    value
                    for value in views
                    if value.view_id == preferred_view_id
                    and value.content_hash == preferred_view_hash
                ),
                None,
            )
        selected: list[InvestmentView] = []
        normalized = None if query is None else query.casefold()
        for value in views:
            if preferred_security_id is not None and value.security_id == preferred_security_id:
                selected.append(value)
                continue
            if normalized is None:
                selected.append(value)
                continue
            identity = self._identity(value.security_id, value.decision_time)
            if normalized in {
                value.security_id.casefold(),
                str(identity["symbol"]).casefold(),
                str(identity["display_name"]).casefold(),
            }:
                selected.append(value)
        if not selected:
            return None
        return max(selected, key=lambda value: (value.decision_time, value.view_id))

    def _identity(self, security_id: str, at: datetime) -> Projection:
        matches = tuple(
            value
            for value in self._security_master.snapshots(at.date())
            if value.security_id == security_id
        )
        if matches:
            value = matches[0]
            industry = self._industry(value)
            return {
                "security_id": security_id,
                "symbol": value.code or security_id,
                "exchange": value.exchange.value,
                "display_name": value.name or value.company_name,
                "industry": industry,
                "identity_resolved": True,
            }
        parts = security_id.split(":")
        exchange = next((item for item in parts if item in {"XSHG", "XSHE", "XBSE"}), "")
        symbol = next((item for item in parts if item.isdigit() and len(item) == 6), security_id)
        return {
            "security_id": security_id,
            "symbol": symbol,
            "exchange": exchange or "unavailable",
            "display_name": symbol,
            "industry": {"code": "unavailable", "display_name": "行业不可用"},
            "identity_resolved": False,
        }

    @staticmethod
    def _industry(value: SecurityIdentitySnapshot) -> Projection:
        if not value.industries:
            return {"code": "unavailable", "display_name": "行业不可用"}
        industry = min(
            value.industries,
            key=lambda item: (item.taxonomy, item.industry_code or ""),
        )
        return {
            "code": industry.industry_code or f"taxonomy:{industry.taxonomy}:unavailable",
            "display_name": industry.industry_name,
        }

    def _project_screen(
        self,
        values: tuple[SignalSnapshot, ...],
        *,
        selected_security_id: str | None,
        views: tuple[InvestmentView, ...] = (),
    ) -> Projection:
        identities = {
            value.security_id: self._identity(value.security_id, value.decision_time)
            for value in values
        }
        # Each row's component contributions come from the exact frozen view the
        # snapshot is bound to — matched on both id and hash, so a newer view for
        # the same security can never supply them.
        bound_views = {
            (item.view_id, item.content_hash): item for item in views
        }
        rows = [
            self._project_signal_row(
                value,
                identity=identities[value.security_id],
                selected=value.security_id == selected_security_id,
                view=bound_views.get((value.investment_view_id, value.investment_view_hash)),
            )
            for value in values
        ]
        selected = next(
            (value for value in values if value.security_id == selected_security_id),
            None,
        )
        selected_projection = None
        peers: list[Projection] = []
        if selected is not None:
            identity = identities[selected.security_id]
            selected_projection = {
                "security_id": selected.security_id,
                "snapshot_id": selected.snapshot_id,
                "display_name": identity["display_name"],
                "symbol": identity["symbol"],
                "industry": identity["industry"],
            }
            industry_code = identity["industry"]["code"]
            if industry_code != "unavailable":
                peers = [
                    {
                        "security_id": value.security_id,
                        "display_name": identities[value.security_id]["display_name"],
                        "symbol": identities[value.security_id]["symbol"],
                        "rank": {"value": value.rank, "display": str(value.rank)},
                        "expected_return": _percent(value.expected_return),
                        "snapshot_id": value.snapshot_id,
                    }
                    for value in values
                    if value.security_id != selected.security_id
                    and identities[value.security_id]["industry"]["code"] == industry_code
                ]
        reference = values[0]
        warning_values: list[str] = []
        if any(not value["identity_resolved"] for value in identities.values()):
            warning_values.append(
                "部分证券展示身份未在 Security Master 解析；保留 security_id/代码且不推断名称。"
            )
        return {
            "screen_id": _content_id(
                "screen",
                {
                    "universe_version_id": reference.universe_version_id,
                    "decision_time": _time(reference.decision_time),
                    "horizon": reference.horizon_trading_days,
                    "snapshots": tuple(value.content_hash for value in values),
                },
            ),
            "universe": {
                "universe_version_id": reference.universe_version_id,
                "display_name": reference.universe_version_id,
                "universe_size": reference.universe_size,
            },
            "decision_time": _time(reference.decision_time),
            "data_cutoff": _time(max(value.data_cutoff for value in values)),
            "data_mode": reference.run_context.data_mode.value,
            "trust_state": reference.trust_state.value,
            "approval_scope": reference.approval_scope.value,
            "model_version_id": reference.model_version_id,
            "factor_version_ids": sorted(
                {item for value in values for item in value.factor_version_ids}
            ),
            "dataset_version_ids": sorted(
                {item for value in values for item in value.dataset_version_ids}
            ),
            "feature_version_ids": sorted(
                {item for value in values for item in value.feature_version_ids}
            ),
            "rows": rows,
            "selected_security": selected_projection,
            "industry_peers": peers,
            "warnings": warning_values,
        }

    @staticmethod
    def _project_signal_row(
        value: SignalSnapshot,
        *,
        identity: Projection,
        selected: bool,
        view: InvestmentView | None = None,
    ) -> Projection:
        previous_rank: Projection = (
            {
                "value": None,
                "display": None,
                "unavailable_reason": "没有同一冻结 Screen 的前序排名。",
            }
            if value.previous_rank is None
            else {
                "value": value.previous_rank,
                "display": str(value.previous_rank),
                "unavailable_reason": None,
            }
        )
        if value.rank_change is None:
            rank_change: Projection = {
                "value": None,
                "display": None,
                "unavailable_reason": "前序排名不可用，不能计算排名变化。",
                "direction": "unavailable",
            }
        else:
            direction = (
                "up" if value.rank_change > 0 else "down" if value.rank_change < 0 else "flat"
            )
            arrow = "↑" if direction == "up" else "↓" if direction == "down" else "→"
            rank_change = {
                "value": value.rank_change,
                "display": f"{arrow}{abs(value.rank_change)}",
                "unavailable_reason": None,
                "direction": direction,
            }
        return {
            "snapshot_id": value.snapshot_id,
            "security": {
                "security_id": value.security_id,
                "symbol": identity["symbol"],
                "display_name": identity["display_name"],
                "exchange": identity["exchange"],
            },
            "industry": identity["industry"],
            "rank": {"value": value.rank, "display": str(value.rank)},
            "previous_rank": previous_rank,
            "rank_change": rank_change,
            "score": _score(value.score),
            "expected_return": _percent(value.expected_return),
            "confidence": _confidence(value.confidence),
            "components": ResearchWorkspaceProjectionService._project_row_components(view),
            "expected_return_interval": (
                ResearchWorkspaceProjectionService._project_return_interval(value, view)
            ),
            "investment_view_id": value.investment_view_id,
            "trust_state": value.trust_state.value,
            "content_hash": value.content_hash,
            "selected": selected,
        }

    @staticmethod
    def _project_row_components(view: InvestmentView | None) -> list[Projection]:
        """Per-row quality / valuation / revision / event contributions.

        Read from the frozen view, never derived from the row score: deriving
        them would create a second source of truth for a governed number.  An
        unavailable or not-applicable component shows an em dash, never a zero.
        """
        if view is None:
            return []
        projected: list[Projection] = []
        for item in view.components:
            contribution = item.expected_return_contribution
            quantified = (
                item.status is InvestmentComponentStatus.QUANTIFIED and contribution is not None
            )
            projected.append({
                "component": item.name,
                "label": _COMPONENT_LABELS.get(item.name, item.name),
                "status": item.status.value,
                "contribution": None if contribution is None else _percent(contribution),
                "display": (
                    _percent(contribution)["display"]
                    if quantified and contribution is not None
                    else "—"
                ),
                "reason": item.status_reason,
                "evidence_ids": list(item.evidence_ids),
            })
        return projected

    @staticmethod
    def _project_return_interval(
        value: SignalSnapshot,
        view: InvestmentView | None,
    ) -> Projection:
        """The horizon expected-return interval shown as a single table column.

        p10/p90 come from the frozen view's distribution.  Without the bound view
        the interval is explicitly unavailable rather than collapsed to the point
        estimate, which would overstate precision.
        """
        if view is None:
            return {
                "horizon_trading_days": value.horizon_trading_days,
                "lower": None,
                "upper": None,
                "display": None,
                "unavailable_reason": "该行没有绑定的冻结 InvestmentView，无法给出区间。",
            }
        lower = _percent(view.expected_return.p10)
        upper = _percent(view.expected_return.p90)
        return {
            "horizon_trading_days": view.horizon_trading_days,
            "lower": lower,
            "upper": upper,
            "display": f"[{lower['display']}, {upper['display']}]",
            "unavailable_reason": None,
        }

    def _project_investment_view(self, value: InvestmentView) -> Projection:
        identity = self._identity(value.security_id, value.decision_time)
        numeric = tuple(
            item.expected_return_contribution
            for item in value.components
            if item.expected_return_contribution is not None
        ) + (value.residual,)
        scale = max((abs(item) for item in numeric), default=Decimal(0))
        components = [self._project_component(item, scale=scale) for item in value.components]
        return {
            "view_id": value.view_id,
            "security": {
                "security_id": value.security_id,
                "symbol": identity["symbol"],
                "exchange": identity["exchange"],
                "display_name": identity["display_name"],
            },
            "decision_time": _time(value.decision_time),
            "horizon": f"{value.horizon_trading_days}D",
            "data_mode": value.run_context.data_mode.value,
            "trust_state": value.trust_state.value,
            "trust_reason": (
                "严格历史输入均通过 PIT trust 与 available_at 截止检查。"
                if value.run_context.data_mode.value == "strict_historical"
                else "该视图使用 normalized_current/current research 输入，不构成历史 PIT 证据。"
            ),
            "distribution": {
                "point": _percent(value.expected_return.point),
                "p10": _percent(value.expected_return.p10),
                "p50": _percent(value.expected_return.p50),
                "p90": _percent(value.expected_return.p90),
                "downside": _percent(value.expected_return.downside),
            },
            "components": components,
            "residual": {
                "status": "quantified",
                "contribution": _percent(value.residual),
                "reason": value.residual_reason,
                "evidence_ids": list(value.residual_evidence_ids),
                "visual": self._visual(value.residual, scale=scale),
            },
            "closure": {
                "status": "passed",
                "displayed_total": _percent(value.reconciled_expected_return)["display"],
                "tolerance": "0",
                "difference": "0",
                "checked_by": value.model_version_id,
            },
            "confidence": _confidence(value.confidence),
            "catalysts": [
                {
                    "catalyst_id": _content_id("catalyst", item),
                    "summary": item,
                    "horizon": f"{value.horizon_trading_days}D",
                    "evidence_ids": [],
                }
                for item in value.catalysts
            ],
            "invalidators": [
                {
                    "invalidator_id": _content_id("invalidator", item),
                    "summary": item,
                    "evidence_ids": [],
                }
                for item in value.invalidators
            ],
            "evidence": [],
            "versions": {
                "dataset_version_ids": list(value.dataset_version_ids),
                "feature_version_ids": list(value.feature_version_ids),
                "model_version_id": value.model_version_id,
                "run_id": value.run_id,
                # A frozen InvestmentView is not automatically an Artifact ledger record.
                # Export will populate this only after a real immutable artifact exists.
                "artifact_id": None,
                "code_version": value.code_version,
                "environment_id": value.environment_id,
                "content_hash": value.content_hash,
            },
            "warnings": (
                []
                if identity["identity_resolved"]
                else ["Security Master 展示身份不可用；未推断公司名称。"]
            ),
        }

    @staticmethod
    def _project_component(value: InvestmentComponent, *, scale: Decimal) -> Projection:
        contribution = value.expected_return_contribution
        return {
            "component": value.name,
            "label": _COMPONENT_LABELS.get(value.name, value.name),
            "status": value.status.value,
            "contribution": None if contribution is None else _percent(contribution),
            "reason": (
                value.status_reason
                if value.status_reason is not None
                else "量化分项已由冻结服务端编译并绑定证据。"
            ),
            "evidence_ids": list(value.evidence_ids),
            "visual": (
                None
                if value.status is not InvestmentComponentStatus.QUANTIFIED or contribution is None
                else ResearchWorkspaceProjectionService._visual(contribution, scale=scale)
            ),
        }

    @staticmethod
    def _visual(value: Decimal, *, scale: Decimal) -> Projection:
        width = Decimal(0) if scale == 0 else abs(value) / scale * Decimal(45)
        start = Decimal(50) - width if value < 0 else Decimal(50)
        return {
            "start_percent": _decimal_text(start),
            "width_percent": _decimal_text(width),
            "direction": "positive" if value > 0 else "negative" if value < 0 else "flat",
        }

    def _project_alpha(
        self,
        snapshots: tuple[SignalSnapshot, ...],
        views: tuple[InvestmentView, ...],
        *,
        selected_security_id: str | None,
    ) -> Projection:
        checked_at = _time(datetime.now(UTC))
        base = {
            "requested_scope": "research_backtest",
            "data_mode": "current_research",
            "deployment_stage": "research",
            "checked_at": checked_at,
        }
        if not snapshots:
            return {
                **base,
                "status": "unavailable",
                "blocked_reasons": [
                    _blocker(
                        "approved_factor_unavailable",
                        "没有 research_backtest scope 的冻结 SignalSnapshot。",
                        "approval_scope:research_backtest",
                    )
                ],
            }
        reference = next(
            (value for value in snapshots if value.security_id == selected_security_id),
            snapshots[0],
        )
        base["data_mode"] = reference.run_context.data_mode.value
        base["deployment_stage"] = reference.run_context.deployment_stage.value
        view = next(
            (value for value in views if value.view_id == reference.investment_view_id),
            None,
        )
        if view is None or view.content_hash != reference.investment_view_hash:
            return {
                **base,
                "status": "unavailable",
                "blocked_reasons": [
                    _blocker(
                        "investment_view_binding_unavailable",
                        "SignalSnapshot 引用的冻结 InvestmentView 不存在或 hash 不匹配。",
                        reference.investment_view_id,
                    )
                ],
            }
        reviews: list[FactorPromotionReview] = []
        try:
            for review_id, review_hash in zip(
                reference.factor_review_ids,
                reference.factor_review_hashes,
            ):
                review = self._factor_reviews.get_review(review_id)
                if review is None or review.content_hash != review_hash:
                    return {
                        **base,
                        "status": "unavailable",
                        "blocked_reasons": [
                            _blocker(
                                "factor_review_binding_unavailable",
                                "冻结 Reviewer 决定不存在或 hash 不匹配。",
                                review_id,
                            )
                        ],
                    }
                reviews.append(review)
        except FactorReviewStoreUnavailable as error:
            return {
                **base,
                "status": "unavailable",
                "blocked_reasons": [
                    _blocker(
                        "factor_review_store_unavailable",
                        str(error),
                        "governance.factor_promotion_reviews",
                    )
                ],
            }
        factor_hashes = dict(zip(reference.factor_version_ids, reference.factor_version_hashes))
        return {
            **base,
            "status": "ready",
            "model": {
                "model_version_id": reference.model_version_id,
                "code_version": view.code_version,
                "environment_id": view.environment_id,
                "investment_view_id": view.view_id,
                "investment_view_hash": view.content_hash,
            },
            "factors": [
                {
                    "factor_version_id": review.factor_version_id,
                    "factor_version_hash": factor_hashes[review.factor_version_id],
                    "lifecycle_status": "production",
                    "review_id": review.review_id,
                    "review_hash": review.content_hash,
                    "validation_report_id": review.validation_report_id,
                    "validation_report_hash": review.validation_report_hash,
                    "scientific_gate_passed": True,
                    "approval": {
                        "approval_id": review.approval.approval_id,
                        "approval_hash": review.approval.content_hash,
                        "scope": review.approval.scope.value,
                        "decision": review.approval.decision.value,
                        "reviewer_id": review.approval.actor_id,
                        "reviewer_role": review.approval.actor_role,
                        "decided_at": _time(review.approval.decided_at),
                        "reason": review.approval.reason,
                    },
                }
                for review in reviews
            ],
        }


__all__ = ["ResearchWorkspaceProjectionService"]
