"""In-memory contract adapter for immutable Expected Return ledger records."""

from __future__ import annotations

from datetime import datetime
from typing import Never

from a_share_platform.domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    InvestmentViewOutcome,
    InvestmentViewOutcomeObservation,
    OutcomeObservationReason,
    OutcomeObservationStatus,
)
from a_share_platform.domain.investment_view import InvestmentView
from a_share_platform.ports.expected_return import (
    ExpectedReturnLedgerConflict,
    ExpectedReturnLedgerUnavailable,
)


class InMemoryExpectedReturnLedgerRepository:
    """Append-only test adapter with identifier and natural-key protection."""

    def __init__(self) -> None:
        self._views: dict[str, InvestmentView] = {}
        self._outcomes: dict[str, InvestmentViewOutcome] = {}
        self._outcome_id_by_view: dict[str, str] = {}
        self._calibrations: dict[str, ExpectedReturnCalibrationRecord] = {}
        self._calibration_id_by_outcome: dict[str, str] = {}

    def append_view(self, value: InvestmentView) -> InvestmentView:
        if not isinstance(value, InvestmentView):
            raise TypeError("value must be an InvestmentView")
        existing = self._views.get(value.view_id)
        if existing is not None:
            if existing.content_hash != value.content_hash:
                raise ExpectedReturnLedgerConflict(
                    f"immutable InvestmentView conflict: {value.view_id}"
                )
            return existing
        self._views[value.view_id] = value
        return value

    def get_view(self, view_id: str) -> InvestmentView | None:
        return self._views.get(view_id)

    def list_views(self) -> tuple[InvestmentView, ...]:
        return tuple(self._views[key] for key in sorted(self._views))

    def append_outcome(self, value: InvestmentViewOutcome) -> InvestmentViewOutcome:
        if not isinstance(value, InvestmentViewOutcome):
            raise TypeError("value must be an InvestmentViewOutcome")
        existing = self._outcomes.get(value.outcome_id)
        if existing is not None:
            if existing.content_hash != value.content_hash:
                raise ExpectedReturnLedgerConflict(
                    f"immutable InvestmentView outcome conflict: {value.outcome_id}"
                )
            return existing
        prior_id = self._outcome_id_by_view.get(value.view_id)
        if prior_id is not None:
            raise ExpectedReturnLedgerConflict(
                f"outcome for view {value.view_id} is immutable; existing={prior_id}"
            )
        self._outcomes[value.outcome_id] = value
        self._outcome_id_by_view[value.view_id] = value.outcome_id
        return value

    def get_outcome(self, outcome_id: str) -> InvestmentViewOutcome | None:
        return self._outcomes.get(outcome_id)

    def outcome_for_view(self, view_id: str) -> InvestmentViewOutcome | None:
        outcome_id = self._outcome_id_by_view.get(view_id)
        return None if outcome_id is None else self._outcomes[outcome_id]

    def list_outcomes(self) -> tuple[InvestmentViewOutcome, ...]:
        return tuple(self._outcomes[key] for key in sorted(self._outcomes))

    def append_calibration(
        self,
        value: ExpectedReturnCalibrationRecord,
    ) -> ExpectedReturnCalibrationRecord:
        if not isinstance(value, ExpectedReturnCalibrationRecord):
            raise TypeError("value must be an ExpectedReturnCalibrationRecord")
        existing = self._calibrations.get(value.calibration_id)
        if existing is not None:
            if existing.content_hash != value.content_hash:
                raise ExpectedReturnLedgerConflict(
                    f"immutable Calibration conflict: {value.calibration_id}"
                )
            return existing
        prior_id = self._calibration_id_by_outcome.get(value.outcome_id)
        if prior_id is not None:
            raise ExpectedReturnLedgerConflict(
                f"Calibration for outcome {value.outcome_id} already exists: {prior_id}"
            )
        self._calibrations[value.calibration_id] = value
        self._calibration_id_by_outcome[value.outcome_id] = value.calibration_id
        return value

    def get_calibration(
        self,
        calibration_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        return self._calibrations.get(calibration_id)

    def calibration_for_outcome(
        self,
        outcome_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        calibration_id = self._calibration_id_by_outcome.get(outcome_id)
        return None if calibration_id is None else self._calibrations[calibration_id]

    def list_calibrations(self) -> tuple[ExpectedReturnCalibrationRecord, ...]:
        return tuple(self._calibrations[key] for key in sorted(self._calibrations))


class UnavailableExpectedReturnLedgerRepository:
    """Fail closed instead of substituting runtime fixtures for durable storage."""

    def __init__(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("unavailable Expected Return ledger reason must not be empty")
        self._reason = reason

    def _raise(self) -> Never:
        raise ExpectedReturnLedgerUnavailable(self._reason)

    def append_view(self, value: InvestmentView) -> InvestmentView:
        del value
        self._raise()

    def get_view(self, view_id: str) -> InvestmentView | None:
        del view_id
        self._raise()

    def list_views(self) -> tuple[InvestmentView, ...]:
        self._raise()

    def append_outcome(self, value: InvestmentViewOutcome) -> InvestmentViewOutcome:
        del value
        self._raise()

    def get_outcome(self, outcome_id: str) -> InvestmentViewOutcome | None:
        del outcome_id
        self._raise()

    def outcome_for_view(self, view_id: str) -> InvestmentViewOutcome | None:
        del view_id
        self._raise()

    def list_outcomes(self) -> tuple[InvestmentViewOutcome, ...]:
        self._raise()

    def append_calibration(
        self,
        value: ExpectedReturnCalibrationRecord,
    ) -> ExpectedReturnCalibrationRecord:
        del value
        self._raise()

    def get_calibration(
        self,
        calibration_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        del calibration_id
        self._raise()

    def calibration_for_outcome(
        self,
        outcome_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        del outcome_id
        self._raise()

    def list_calibrations(self) -> tuple[ExpectedReturnCalibrationRecord, ...]:
        self._raise()


class UnavailableInvestmentViewOutcomeSource:
    """Honest runtime adapter used until a real price policy is approved."""

    def __init__(self, *, reason: str, source_policy_version: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("unavailable outcome source reason must not be empty")
        if not isinstance(source_policy_version, str) or not source_policy_version.strip():
            raise ValueError("source_policy_version must not be empty")
        self._reason = reason
        self._source_policy_version = source_policy_version

    def observe(
        self,
        *,
        view: InvestmentView,
        evaluated_at: datetime,
    ) -> InvestmentViewOutcomeObservation:
        if not isinstance(view, InvestmentView):
            raise TypeError("view must be an InvestmentView")
        return InvestmentViewOutcomeObservation(
            view_id=view.view_id,
            security_id=view.security_id,
            decision_time=view.decision_time,
            horizon_trading_days=view.horizon_trading_days,
            evaluated_at=evaluated_at,
            status=OutcomeObservationStatus.UNAVAILABLE,
            source_policy_version=self._source_policy_version,
            reason_code=OutcomeObservationReason.SOURCE_UNQUALIFIED,
            reason=self._reason,
        )


__all__ = [
    "InMemoryExpectedReturnLedgerRepository",
    "UnavailableExpectedReturnLedgerRepository",
    "UnavailableInvestmentViewOutcomeSource",
]
