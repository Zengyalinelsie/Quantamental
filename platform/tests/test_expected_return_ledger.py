import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

from a_share_platform.adapters.memory.expected_return import (
    InMemoryExpectedReturnLedgerRepository,
    UnavailableExpectedReturnLedgerRepository,
)
from a_share_platform.application.expected_return_ledger import (
    ExpectedReturnLedgerIntegrityError,
    ExpectedReturnLedgerNotFound,
    ExpectedReturnLedgerService,
)
from a_share_platform.domain.expected_return import (
    ExpectedReturnCompilerV0,
    InvestmentViewOutcome,
)
from a_share_platform.ports.expected_return import (
    ExpectedReturnLedgerConflict,
    ExpectedReturnLedgerUnavailable,
)
from tests.test_expected_return_compiler import DECISION_TIME, request


def outcome_for(view: object, *, outcome_id: str = "outcome:view:001") -> InvestmentViewOutcome:
    return InvestmentViewOutcome(
        outcome_id=outcome_id,
        view_id=view.view_id,  # type: ignore[attr-defined]
        security_id=view.security_id,  # type: ignore[attr-defined]
        decision_time=view.decision_time,  # type: ignore[attr-defined]
        horizon_trading_days=view.horizon_trading_days,  # type: ignore[attr-defined]
        realized_at=DECISION_TIME + timedelta(days=100),
        realized_return=Decimal("-0.03"),
        dataset_version_id="dataset:realized-return:v1",
        source_policy_version="outcome-price-policy:test:v1",
        source_available_at=DECISION_TIME + timedelta(days=100),
        recorded_at=DECISION_TIME + timedelta(days=101),
    )


class ExpectedReturnLedgerServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryExpectedReturnLedgerRepository()
        self.service = ExpectedReturnLedgerService(self.repository)
        self.view = ExpectedReturnCompilerV0().compile(request())

    def test_view_append_is_idempotent_and_same_id_different_content_conflicts(self) -> None:
        first = self.service.record_view(self.view)
        second = self.service.record_view(self.view)

        self.assertIs(first, second)
        self.assertEqual(self.service.get_view(self.view.view_id), self.view)
        self.assertEqual(self.service.list_views(), (self.view,))

        changed = replace(self.view, catalysts=("另一个催化剂",))
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "InvestmentView"):
            self.service.record_view(changed)

    def test_outcome_requires_the_exact_persisted_view_identity(self) -> None:
        missing = outcome_for(self.view)
        with self.assertRaisesRegex(ExpectedReturnLedgerNotFound, "InvestmentView"):
            self.service.record_outcome(missing)

        self.service.record_view(self.view)
        mismatched = replace(missing, security_id="security:CN:000001:XSHE")
        with self.assertRaisesRegex(ExpectedReturnLedgerIntegrityError, "identity"):
            self.service.record_outcome(mismatched)

    def test_one_outcome_per_view_is_immutable_and_idempotent(self) -> None:
        self.service.record_view(self.view)
        outcome = outcome_for(self.view)

        first = self.service.record_outcome(outcome)
        second = self.service.record_outcome(outcome)
        self.assertIs(first, second)
        self.assertEqual(self.service.outcome_for_view(self.view.view_id), outcome)
        self.assertEqual(self.service.list_outcomes(), (outcome,))

        rewritten = replace(
            outcome,
            outcome_id="outcome:view:rewritten",
            realized_return=Decimal("0.25"),
        )
        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "outcome.*view"):
            self.service.record_outcome(rewritten)

    def test_calibration_is_derived_from_frozen_view_and_outcome(self) -> None:
        self.service.record_view(self.view)
        outcome = self.service.record_outcome(outcome_for(self.view))
        recorded_at = outcome.recorded_at + timedelta(minutes=1)

        first = self.service.record_calibration(
            calibration_id="calibration:view:001",
            view_id=self.view.view_id,
            outcome_id=outcome.outcome_id,
            recorded_at=recorded_at,
        )
        second = self.service.record_calibration(
            calibration_id="calibration:view:001",
            view_id=self.view.view_id,
            outcome_id=outcome.outcome_id,
            recorded_at=recorded_at,
        )

        self.assertIs(first, second)
        self.assertEqual(first.predicted_return, Decimal("0.045"))
        self.assertEqual(first.realized_return, Decimal("-0.03"))
        self.assertEqual(first.absolute_error, Decimal("0.075"))
        self.assertEqual(self.service.calibration_for_outcome(outcome.outcome_id), first)

        with self.assertRaisesRegex(ExpectedReturnLedgerConflict, "Calibration"):
            self.service.record_calibration(
                calibration_id="calibration:view:001",
                view_id=self.view.view_id,
                outcome_id=outcome.outcome_id,
                recorded_at=recorded_at + timedelta(minutes=1),
            )

    def test_calibration_rejects_missing_or_cross_bound_records(self) -> None:
        self.service.record_view(self.view)
        with self.assertRaisesRegex(ExpectedReturnLedgerNotFound, "outcome"):
            self.service.record_calibration(
                calibration_id="calibration:missing",
                view_id=self.view.view_id,
                outcome_id="outcome:missing",
                recorded_at=DECISION_TIME + timedelta(days=101),
            )

        outcome = self.service.record_outcome(outcome_for(self.view))
        with self.assertRaisesRegex(ExpectedReturnLedgerIntegrityError, "same view"):
            self.service.record_calibration(
                calibration_id="calibration:cross-bound",
                view_id="investment-view:other",
                outcome_id=outcome.outcome_id,
                recorded_at=outcome.recorded_at,
            )


class UnavailableExpectedReturnLedgerRepositoryTest(unittest.TestCase):
    def test_unconfigured_ledger_fails_closed_without_runtime_fixtures(self) -> None:
        repository = UnavailableExpectedReturnLedgerRepository(
            "durable Expected Return ledger is not configured"
        )
        service = ExpectedReturnLedgerService(repository)

        with self.assertRaisesRegex(ExpectedReturnLedgerUnavailable, "not configured"):
            service.list_views()
        with self.assertRaisesRegex(ExpectedReturnLedgerUnavailable, "not configured"):
            service.record_view(ExpectedReturnCompilerV0().compile(request()))


if __name__ == "__main__":
    unittest.main()
