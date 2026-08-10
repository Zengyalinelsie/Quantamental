import math
import statistics
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode
from a_share_platform.domain.timing import (
    PASSIVE_VOLATILITY_FORMULA_VERSION,
    BenchmarkCloseBatch,
    BenchmarkCloseObservation,
    estimate_passive_volatility,
)

RETRIEVED_AT = datetime(2026, 8, 10, 7, 59, tzinfo=UTC)


def close_rows() -> tuple[BenchmarkCloseObservation, ...]:
    return tuple(
        BenchmarkCloseObservation(
            benchmark_id="index:000300",
            session_date=date(2026, 7, 21) + timedelta(days=index),
            unadjusted_close=Decimal(100 + index * index),
        )
        for index in range(21)
    )


def batch(**overrides: object) -> BenchmarkCloseBatch:
    values: dict[str, object] = {
        "benchmark_id": "index:000300",
        "rows": close_rows(),
        "provider_id": "baostock_sdk",
        "retrieved_at": RETRIEVED_AT,
        "adjustment_mode": "unadjusted",
        "trust_state": DataTrustState.NORMALIZED_CURRENT,
        "data_mode": DataMode.CURRENT_RESEARCH,
    }
    values.update(overrides)
    return BenchmarkCloseBatch(**values)  # type: ignore[arg-type]


class TimingBaselineMathTest(unittest.TestCase):
    def test_formula_is_20_unadjusted_close_log_returns_sample_std_times_sqrt_244(
        self,
    ) -> None:
        value = batch()

        estimate = estimate_passive_volatility(value)

        closes = [float(row.unadjusted_close) for row in value.rows]
        returns = [math.log(current / previous) for previous, current in pairwise(closes)]
        expected = statistics.stdev(returns) * math.sqrt(244)
        population_result = statistics.pstdev(returns) * math.sqrt(244)
        self.assertEqual(estimate.lookback_return_count, 20)
        self.assertEqual(estimate.annualization_sessions, 244)
        self.assertEqual(estimate.formula_version, PASSIVE_VOLATILITY_FORMULA_VERSION)
        self.assertAlmostEqual(float(estimate.annualized_volatility_ratio), expected, places=14)
        self.assertNotAlmostEqual(
            float(estimate.annualized_volatility_ratio), population_result, places=10
        )

    def test_exactly_21_strictly_ordered_positive_closes_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly 21"):
            batch(rows=close_rows()[:-1])

        rows = close_rows()
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            batch(rows=(*rows[:10], rows[9], *rows[11:]))
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            batch(rows=(*rows[:9], rows[10], rows[9], *rows[11:]))
        with self.assertRaisesRegex(ValueError, "positive"):
            replace(rows[0], unadjusted_close=Decimal(0))

    def test_current_research_input_cannot_be_relabelled_as_pit(self) -> None:
        for overrides in (
            {"adjustment_mode": "forward"},
            {"trust_state": DataTrustState.PIT_VERIFIED},
            {"data_mode": DataMode.STRICT_HISTORICAL},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                batch(**overrides)


if __name__ == "__main__":
    unittest.main()
