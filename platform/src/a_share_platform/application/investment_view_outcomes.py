"""Provider-neutral maturity scan for append-only InvestmentView outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerService,
)
from a_share_platform.domain.expected_return import (
    InvestmentViewOutcome,
    InvestmentViewOutcomeObservation,
    OutcomeObservationStatus,
)
from a_share_platform.domain.investment_view import InvestmentView
from a_share_platform.domain.run_context import DeploymentStage
from a_share_platform.ports.expected_return import (
    ExpectedReturnLedgerRepository,
    InvestmentViewOutcomeSource,
)


class OutcomeWorkItemStatus(StrEnum):
    ALREADY_RECORDED = "already_recorded"
    PENDING = "pending"
    UNAVAILABLE = "unavailable"
    MATURE = "mature"


@dataclass(frozen=True)
class OutcomeWorkItem:
    view_id: str
    status: OutcomeWorkItemStatus
    reason_code: str | None
    reason: str | None
    source_policy_version: str | None
    outcome: InvestmentViewOutcome | None
    write_performed: bool


@dataclass(frozen=True)
class OutcomeMaturityBatch:
    evaluated_at: datetime
    items: tuple[OutcomeWorkItem, ...]

    @property
    def writes_performed(self) -> bool:
        return any(item.write_performed for item in self.items)

    @property
    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for item in self.items:
            key = item.status.value
            result[key] = result.get(key, 0) + 1
        return result


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class InvestmentViewOutcomeMaturityService:
    """Scan frozen views; the source owns calendar and adjusted-return policy."""

    def __init__(
        self,
        repository: ExpectedReturnLedgerRepository,
        source: InvestmentViewOutcomeSource,
    ) -> None:
        self._repository = repository
        self._source = source
        self._ledger = ExpectedReturnLedgerService(repository)

    def evaluate(self, *, evaluated_at: datetime) -> OutcomeMaturityBatch:
        return self._scan(evaluated_at=evaluated_at, execute=False)

    def ensure(self, *, evaluated_at: datetime) -> OutcomeMaturityBatch:
        return self._scan(evaluated_at=evaluated_at, execute=True)

    def _scan(self, *, evaluated_at: datetime, execute: bool) -> OutcomeMaturityBatch:
        evaluated_at = _aware(evaluated_at, "evaluated_at")
        items = tuple(
            self._process_view(view, evaluated_at=evaluated_at, execute=execute)
            for view in sorted(self._repository.list_views(), key=lambda value: value.view_id)
        )
        return OutcomeMaturityBatch(evaluated_at=evaluated_at, items=items)

    def _process_view(
        self,
        view: InvestmentView,
        *,
        evaluated_at: datetime,
        execute: bool,
    ) -> OutcomeWorkItem:
        existing = self._repository.outcome_for_view(view.view_id)
        if existing is not None:
            return OutcomeWorkItem(
                view_id=view.view_id,
                status=OutcomeWorkItemStatus.ALREADY_RECORDED,
                reason_code=None,
                reason=None,
                source_policy_version=existing.source_policy_version,
                outcome=existing,
                write_performed=False,
            )
        if view.run_context.deployment_stage is not DeploymentStage.RESEARCH:
            return OutcomeWorkItem(
                view_id=view.view_id,
                status=OutcomeWorkItemStatus.UNAVAILABLE,
                reason_code="deployment_stage_not_authorized",
                reason="P11 is not authorized; only research InvestmentViews may be evaluated",
                source_policy_version=None,
                outcome=None,
                write_performed=False,
            )

        observation = self._source.observe(view=view, evaluated_at=evaluated_at)
        self._validate_observation(view, observation, evaluated_at)
        if observation.status is not OutcomeObservationStatus.MATURE:
            return OutcomeWorkItem(
                view_id=view.view_id,
                status=OutcomeWorkItemStatus(observation.status.value),
                reason_code=(
                    None
                    if observation.reason_code is None
                    else observation.reason_code.value
                ),
                reason=observation.reason,
                source_policy_version=observation.source_policy_version,
                outcome=None,
                write_performed=False,
            )

        if (
            observation.realized_at is None
            or observation.realized_return is None
            or observation.dataset_version_id is None
            or observation.source_available_at is None
        ):
            raise ValueError("mature outcome source observation is incomplete")
        outcome = InvestmentViewOutcome(
            outcome_id=f"investment-view-outcome:{view.content_hash}",
            view_id=view.view_id,
            security_id=view.security_id,
            decision_time=view.decision_time,
            horizon_trading_days=view.horizon_trading_days,
            realized_at=observation.realized_at,
            realized_return=observation.realized_return,
            dataset_version_id=observation.dataset_version_id,
            source_policy_version=observation.source_policy_version,
            source_available_at=observation.source_available_at,
            recorded_at=evaluated_at,
        )
        persisted = self._ledger.record_outcome(outcome) if execute else outcome
        return OutcomeWorkItem(
            view_id=view.view_id,
            status=OutcomeWorkItemStatus.MATURE,
            reason_code=None,
            reason=None,
            source_policy_version=observation.source_policy_version,
            outcome=persisted,
            write_performed=execute,
        )

    @staticmethod
    def _validate_observation(
        view: InvestmentView,
        observation: InvestmentViewOutcomeObservation,
        evaluated_at: datetime,
    ) -> None:
        if not isinstance(observation, InvestmentViewOutcomeObservation):
            raise TypeError(
                "outcome source must return an InvestmentViewOutcomeObservation"
            )
        if (
            observation.view_id != view.view_id
            or observation.security_id != view.security_id
            or observation.decision_time != view.decision_time
            or observation.horizon_trading_days != view.horizon_trading_days
            or observation.evaluated_at != evaluated_at
        ):
            raise ValueError(
                f"outcome source identity mismatch for InvestmentView {view.view_id}"
            )


__all__ = [
    "InvestmentViewOutcomeMaturityService",
    "OutcomeMaturityBatch",
    "OutcomeWorkItem",
    "OutcomeWorkItemStatus",
]
