import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from a_share_platform.adapters.providers.baostock_guard import BaostockGuard
from a_share_platform.adapters.providers.baostock_timing import (
    BaostockTimingBenchmarkSource,
)
from a_share_platform.domain.pit import DataTrustState
from a_share_platform.domain.run_context import DataMode

NOW = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)


class FakeResult:
    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.error_code = "0"
        self.error_msg = "success"
        self.fields = fields
        self._rows = iter(rows)
        self._current: list[str] | None = None

    def next(self) -> bool:
        try:
            self._current = next(self._rows)
        except StopIteration:
            return False
        return True

    def get_row_data(self) -> list[str]:
        assert self._current is not None
        return self._current


class FakeBaostock:
    def __init__(self) -> None:
        self.history_calls: list[dict[str, object]] = []
        self.logged_out = False

    def login(self) -> FakeResult:
        return FakeResult([], [])

    def logout(self) -> None:
        self.logged_out = True

    def query_history_k_data_plus(self, **kwargs: object) -> FakeResult:
        self.history_calls.append(kwargs)
        end = date.fromisoformat(str(kwargs["end_date"]))
        rows = [
            [
                (end - timedelta(days=20 - index)).isoformat(),
                str(kwargs["code"]),
                str(100 + index),
            ]
            for index in range(21)
        ]
        return FakeResult(str(kwargs["fields"]).split(","), rows)


class BaostockTimingBenchmarkSourceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_fetches_only_supported_csi_benchmarks_with_unadjusted_daily_contract(
        self,
    ) -> None:
        module = FakeBaostock()
        guard = BaostockGuard(
            state_directory=Path(self.temp.name),
            clock=lambda: NOW,
            minimum_interval_seconds=0,
        )
        source = BaostockTimingBenchmarkSource(
            module_loader=lambda _name: module,
            clock=lambda: NOW,
            baostock_guard=guard,
        )

        value = source.fetch_recent_closes(
            benchmark_id="index:000300",
            end_session=date(2026, 8, 10),
        )

        self.assertEqual(len(value.rows), 21)
        self.assertEqual(value.rows[-1].session_date, date(2026, 8, 10))
        self.assertEqual(value.provider_id, "baostock_sdk")
        self.assertEqual(value.adjustment_mode, "unadjusted")
        self.assertEqual(value.trust_state, DataTrustState.NORMALIZED_CURRENT)
        self.assertEqual(value.data_mode, DataMode.CURRENT_RESEARCH)
        self.assertEqual(module.history_calls[0]["code"], "sh.000300")
        self.assertEqual(module.history_calls[0]["frequency"], "d")
        self.assertEqual(module.history_calls[0]["adjustflag"], "3")
        self.assertEqual(module.history_calls[0]["fields"], "date,code,close")
        self.assertTrue(module.logged_out)
        self.assertEqual(
            [item.operation for item in guard.attempts(date(2026, 8, 10))],
            ["login", "query_history_k_data_plus", "logout"],
        )

    def test_csi500_maps_to_the_provider_index_code(self) -> None:
        module = FakeBaostock()
        source = BaostockTimingBenchmarkSource(
            module_loader=lambda _name: module,
            clock=lambda: NOW,
            baostock_guard=BaostockGuard(
                state_directory=Path(self.temp.name),
                clock=lambda: NOW,
                minimum_interval_seconds=0,
            ),
        )

        source.fetch_recent_closes(
            benchmark_id="index:000905",
            end_session=date(2026, 8, 10),
        )

        self.assertEqual(module.history_calls[0]["code"], "sh.000905")

    def test_unsupported_benchmark_fails_before_opening_a_provider_session(self) -> None:
        module = FakeBaostock()
        source = BaostockTimingBenchmarkSource(
            module_loader=lambda _name: module,
            clock=lambda: NOW,
            baostock_guard=BaostockGuard(
                state_directory=Path(self.temp.name),
                clock=lambda: NOW,
                minimum_interval_seconds=0,
            ),
        )

        with self.assertRaisesRegex(ValueError, "supported CSI benchmark"):
            source.fetch_recent_closes(
                benchmark_id="index:000852",
                end_session=date(2026, 8, 10),
            )
        self.assertEqual(module.history_calls, [])


if __name__ == "__main__":
    unittest.main()
