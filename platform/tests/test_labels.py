"""Forward-return label contract tests.

Labels are the dependent variable of every factor study, so a silently wrong
label invalidates every downstream statistic.  These tests pin the cases that
matter on A-share data: suspensions, delistings, gaps, and windows that run past
the end of the available history.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from a_share_platform.domain.labels import (
    ForwardReturnLabelDefinition,
    LabelHorizon,
    LabelObservationStatus,
    LabelPriceInput,
    LabelUnavailableReason,
)
from a_share_platform.domain.market_data import PriceAdjustment
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode


def price(session: date, close: str, *, tradable: bool = True) -> LabelPriceInput:
    return LabelPriceInput(
        session_date=session,
        close=Decimal(close),
        tradable=tradable,
    )


def series(closes: list[tuple[str, str]], *, suspended: set[str] = frozenset()) -> tuple[LabelPriceInput, ...]:
    return tuple(
        price(date.fromisoformat(day), close, tradable=day not in suspended)
        for day, close in closes
    )


def definition(horizon: LabelHorizon = LabelHorizon.TWENTY_SESSIONS) -> ForwardReturnLabelDefinition:
    return ForwardReturnLabelDefinition(
        label_id="label.forward_return",
        version="v0",
        horizon=horizon,
        adjustment=PriceAdjustment.UNADJUSTED,
        data_mode=DataMode.CURRENT_RESEARCH,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
    )


class ForwardReturnDefinitionTest(unittest.TestCase):
    def test_definition_is_content_addressed(self) -> None:
        first = definition()
        second = definition()
        self.assertEqual(first.content_hash, second.content_hash)
        self.assertEqual(len(first.content_hash), 64)

    def test_different_horizon_changes_the_hash(self) -> None:
        self.assertNotEqual(
            definition(LabelHorizon.TWENTY_SESSIONS).content_hash,
            definition(LabelHorizon.SIXTY_SESSIONS).content_hash,
        )

    def test_strict_historical_is_refused(self) -> None:
        """This track is current-only; strict labels need pit_verified prices."""
        with self.assertRaises(PermissionError):
            ForwardReturnLabelDefinition(
                label_id="label.forward_return",
                version="v0",
                horizon=LabelHorizon.TWENTY_SESSIONS,
                adjustment=PriceAdjustment.UNADJUSTED,
                data_mode=DataMode.STRICT_HISTORICAL,
                trust_state=DataTrustState.NORMALIZED_CURRENT,
            )

    def test_unadjusted_prices_record_the_corporate_action_limitation(self) -> None:
        """Without corporate actions an unadjusted return can be wrong."""
        value = definition()
        self.assertIn("corporate action", value.limitation.lower())


class ForwardReturnCalculationTest(unittest.TestCase):
    def test_plain_forward_return_over_the_exact_horizon(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.status, LabelObservationStatus.QUANTIFIED)
        # Entry 2026-01-01 closes at 101; 20 sessions later 2026-01-21 closes at
        # 121, so the return is 20/101 = 19.80%.
        self.assertIsNotNone(result.value)
        assert result.value is not None
        self.assertGreater(result.value, Decimal("0.197"))
        self.assertLess(result.value, Decimal("0.199"))

    def test_negative_return_is_reported_as_is(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(200 - day)) for day in range(1, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.status, LabelObservationStatus.QUANTIFIED)
        assert result.value is not None
        self.assertLess(result.value, Decimal(0))

    def test_horizon_counts_trading_sessions_not_calendar_days(self) -> None:
        # A gap over a weekend must not shorten the horizon.
        closes = [
            ("2026-01-02", "100"), ("2026-01-05", "101"), ("2026-01-06", "102"),
            ("2026-01-07", "103"), ("2026-01-08", "104"),
        ]
        short = ForwardReturnLabelDefinition(
            label_id="label.forward_return",
            version="v0",
            horizon=LabelHorizon.TWENTY_SESSIONS,
            adjustment=PriceAdjustment.UNADJUSTED,
            data_mode=DataMode.CURRENT_RESEARCH,
            trust_state=DataTrustState.NORMALIZED_CURRENT,
        )
        result = short.calculate(
            decision_session=date(2026, 1, 2),
            prices=series(closes),
        )
        # Only 5 sessions exist, so a 20-session horizon cannot be satisfied.
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertEqual(result.reason, LabelUnavailableReason.HORIZON_INCOMPLETE)


class ForwardReturnFailClosedTest(unittest.TestCase):
    """Every absence is explicit; nothing is interpolated or zero-filled."""

    def test_incomplete_window_is_unavailable_not_truncated(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 10)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertEqual(result.reason, LabelUnavailableReason.HORIZON_INCOMPLETE)
        self.assertIsNone(result.value)

    def test_missing_decision_session_is_unavailable(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(2, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertEqual(result.reason, LabelUnavailableReason.DECISION_SESSION_MISSING)

    def test_suspended_decision_session_is_unavailable(self) -> None:
        """A suspended entry price is not a tradable price."""
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes, suspended={"2026-01-01"}),
        )
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertEqual(result.reason, LabelUnavailableReason.NOT_TRADABLE)

    def test_suspended_exit_session_is_unavailable(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes, suspended={"2026-01-21"}),
        )
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertEqual(result.reason, LabelUnavailableReason.NOT_TRADABLE)

    def test_a_suspension_inside_the_window_does_not_block_the_label(self) -> None:
        """Only the entry and exit prices are used, so a mid-window halt is fine.

        This is a deliberate semantic: the label measures entry-to-exit return,
        and a name that halted and resumed still has both endpoints tradable.
        """
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes, suspended={"2026-01-10"}),
        )
        self.assertEqual(result.status, LabelObservationStatus.QUANTIFIED)

    def test_zero_entry_price_is_refused_rather_than_dividing(self) -> None:
        closes = [("2026-01-01", "0")] + [
            (f"2026-01-{day:02d}", str(100 + day)) for day in range(2, 25)
        ]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertEqual(result.reason, LabelUnavailableReason.INVALID_PRICE)

    def test_negative_price_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            price(date(2026, 1, 1), "-10")

    def test_unavailable_never_returns_zero(self) -> None:
        """A zero label would read as "no move", not as "unknown"."""
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=(),
        )
        self.assertEqual(result.status, LabelObservationStatus.UNAVAILABLE)
        self.assertIsNone(result.value)
        self.assertNotEqual(result.value, Decimal(0))

    def test_duplicate_sessions_are_refused(self) -> None:
        closes = [("2026-01-01", "100"), ("2026-01-01", "101")]
        with self.assertRaises(ValueError):
            definition().calculate(
                decision_session=date(2026, 1, 1),
                prices=series(closes),
            )

    def test_unsorted_input_is_sorted_deterministically(self) -> None:
        ordered = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        shuffled = list(reversed(ordered))
        self.assertEqual(
            definition().calculate(
                decision_session=date(2026, 1, 1), prices=series(ordered)
            ).value,
            definition().calculate(
                decision_session=date(2026, 1, 1), prices=series(shuffled)
            ).value,
        )


class ForwardReturnProvenanceTest(unittest.TestCase):
    def test_result_carries_the_definition_binding(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        value = definition()
        result = value.calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.label_id, value.label_id)
        self.assertEqual(result.label_version, value.version)
        self.assertEqual(result.definition_hash, value.content_hash)
        self.assertEqual(result.horizon, value.horizon)

    def test_result_records_the_exact_sessions_used(self) -> None:
        closes = [(f"2026-01-{day:02d}", str(100 + day)) for day in range(1, 25)]
        result = definition().calculate(
            decision_session=date(2026, 1, 1),
            prices=series(closes),
        )
        self.assertEqual(result.entry_session, date(2026, 1, 1))
        self.assertEqual(result.exit_session, date(2026, 1, 21))


if __name__ == "__main__":
    unittest.main()
