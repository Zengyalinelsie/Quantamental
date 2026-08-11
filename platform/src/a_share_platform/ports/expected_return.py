"""Persistence port for append-only Expected Return decision records."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.expected_return import (
    ExpectedReturnCalibrationRecord,
    InvestmentViewOutcome,
)
from a_share_platform.domain.investment_view import InvestmentView


class ExpectedReturnLedgerConflict(RuntimeError):
    """An immutable identifier or natural record key was reused."""


class ExpectedReturnLedgerUnavailable(RuntimeError):
    """The durable Expected Return ledger is unavailable or unconfigured."""


class ExpectedReturnLedgerRepository(Protocol):
    def append_view(self, value: InvestmentView) -> InvestmentView: ...

    def get_view(self, view_id: str) -> InvestmentView | None: ...

    def list_views(self) -> tuple[InvestmentView, ...]: ...

    def append_outcome(self, value: InvestmentViewOutcome) -> InvestmentViewOutcome: ...

    def get_outcome(self, outcome_id: str) -> InvestmentViewOutcome | None: ...

    def outcome_for_view(self, view_id: str) -> InvestmentViewOutcome | None: ...

    def list_outcomes(self) -> tuple[InvestmentViewOutcome, ...]: ...

    def append_calibration(
        self,
        value: ExpectedReturnCalibrationRecord,
    ) -> ExpectedReturnCalibrationRecord: ...

    def get_calibration(
        self,
        calibration_id: str,
    ) -> ExpectedReturnCalibrationRecord | None: ...

    def calibration_for_outcome(
        self,
        outcome_id: str,
    ) -> ExpectedReturnCalibrationRecord | None: ...

    def list_calibrations(self) -> tuple[ExpectedReturnCalibrationRecord, ...]: ...


__all__ = [
    "ExpectedReturnLedgerConflict",
    "ExpectedReturnLedgerRepository",
    "ExpectedReturnLedgerUnavailable",
]
