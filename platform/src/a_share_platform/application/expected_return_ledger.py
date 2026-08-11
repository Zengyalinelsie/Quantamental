"""Application service for immutable InvestmentView outcome/calibration records."""

from __future__ import annotations

from datetime import datetime

from a_share_platform.domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    InvestmentViewOutcome,
)
from a_share_platform.domain.investment_view import InvestmentView
from a_share_platform.ports.expected_return import ExpectedReturnLedgerRepository


class ExpectedReturnLedgerNotFound(LookupError):
    """A referenced immutable ledger record does not exist."""


class ExpectedReturnLedgerIntegrityError(ValueError):
    """Cross-record identity or lineage does not close."""


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class ExpectedReturnLedgerService:
    def __init__(self, repository: ExpectedReturnLedgerRepository) -> None:
        self._repository = repository

    def record_view(self, value: InvestmentView) -> InvestmentView:
        if not isinstance(value, InvestmentView):
            raise TypeError("value must be an InvestmentView")
        return self._repository.append_view(value)

    def get_view(self, view_id: str) -> InvestmentView | None:
        return self._repository.get_view(_identifier(view_id, "view_id"))

    def list_views(self) -> tuple[InvestmentView, ...]:
        return self._repository.list_views()

    def record_outcome(self, value: InvestmentViewOutcome) -> InvestmentViewOutcome:
        if not isinstance(value, InvestmentViewOutcome):
            raise TypeError("value must be an InvestmentViewOutcome")
        view = self._repository.get_view(value.view_id)
        if view is None:
            raise ExpectedReturnLedgerNotFound(
                f"InvestmentView does not exist: {value.view_id}"
            )
        if (
            value.security_id != view.security_id
            or value.decision_time != view.decision_time
            or value.horizon_trading_days != view.horizon_trading_days
        ):
            raise ExpectedReturnLedgerIntegrityError(
                "outcome identity does not match the persisted InvestmentView"
            )
        return self._repository.append_outcome(value)

    def get_outcome(self, outcome_id: str) -> InvestmentViewOutcome | None:
        return self._repository.get_outcome(_identifier(outcome_id, "outcome_id"))

    def outcome_for_view(self, view_id: str) -> InvestmentViewOutcome | None:
        return self._repository.outcome_for_view(_identifier(view_id, "view_id"))

    def list_outcomes(self) -> tuple[InvestmentViewOutcome, ...]:
        return self._repository.list_outcomes()

    def record_calibration(
        self,
        *,
        calibration_id: str,
        view_id: str,
        outcome_id: str,
        recorded_at: datetime,
    ) -> ExpectedReturnCalibrationRecord:
        calibration_id = _identifier(calibration_id, "calibration_id")
        view_id = _identifier(view_id, "view_id")
        outcome_id = _identifier(outcome_id, "outcome_id")
        outcome = self._repository.get_outcome(outcome_id)
        if outcome is None:
            raise ExpectedReturnLedgerNotFound(
                f"InvestmentView outcome does not exist: {outcome_id}"
            )
        if outcome.view_id != view_id:
            raise ExpectedReturnLedgerIntegrityError(
                "calibration view and outcome must reference the same view"
            )
        view = self._repository.get_view(view_id)
        if view is None:
            raise ExpectedReturnLedgerNotFound(f"InvestmentView does not exist: {view_id}")
        value = ExpectedReturnCalibrationRecord.from_view_and_outcome(
            calibration_id=calibration_id,
            view=view,
            outcome=outcome,
            recorded_at=recorded_at,
        )
        return self._repository.append_calibration(value)

    def get_calibration(
        self,
        calibration_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        return self._repository.get_calibration(
            _identifier(calibration_id, "calibration_id")
        )

    def calibration_for_outcome(
        self,
        outcome_id: str,
    ) -> ExpectedReturnCalibrationRecord | None:
        return self._repository.calibration_for_outcome(
            _identifier(outcome_id, "outcome_id")
        )

    def list_calibrations(self) -> tuple[ExpectedReturnCalibrationRecord, ...]:
        return self._repository.list_calibrations()


__all__ = [
    "ExpectedReturnLedgerIntegrityError",
    "ExpectedReturnLedgerNotFound",
    "ExpectedReturnLedgerService",
]
