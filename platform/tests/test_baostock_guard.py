import multiprocessing
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from a_share_platform.adapters.providers.baostock_guard import (
    BaostockCooldownActive,
    BaostockGuard,
    BaostockQuotaExceeded,
    BaostockSessionBusy,
)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


class RestrictedResult:
    error_code = "1"
    error_msg = "访问频繁，当前请求已进入黑名单限制"


def _compete_for_session(state_directory: str, result: object) -> None:
    guard = BaostockGuard(
        state_directory=Path(state_directory),
        minimum_interval_seconds=0,
    )
    try:
        with guard.session():
            result.put("acquired")  # type: ignore[attr-defined]
    except BaostockSessionBusy:
        result.put("busy")  # type: ignore[attr-defined]


class BaostockGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_directory = Path(self.temp.name)
        self.clock = MutableClock(datetime(2026, 8, 10, 15, 59, 59, tzinfo=UTC))

    def guard(self, **overrides: object) -> BaostockGuard:
        options: dict[str, object] = {
            "state_directory": self.state_directory,
            "clock": self.clock,
            "sleeper": self.clock.advance,
            "minimum_interval_seconds": 0,
        }
        options.update(overrides)
        return BaostockGuard(**options)  # type: ignore[arg-type]

    def test_global_session_lock_is_nonblocking_across_processes(self) -> None:
        context = multiprocessing.get_context("spawn")
        result = context.Queue()
        guard = self.guard()

        with guard.session():
            process = context.Process(
                target=_compete_for_session,
                args=(str(self.state_directory), result),
            )
            process.start()
            process.join(timeout=10)

        self.assertFalse(process.is_alive())
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(result.get(timeout=1), "busy")

        with self.guard().session():
            pass

    def test_usage_resets_at_asia_shanghai_day_boundary(self) -> None:
        guard = self.guard()
        with guard.session() as session:
            session.call("login", lambda: "ok")
            self.clock.advance(2)
            session.call("query_stock_basic", lambda: "ok")

        first = guard.daily_usage(date(2026, 8, 10))
        second = guard.daily_usage(date(2026, 8, 11))
        self.assertEqual(first.provider_call_count, 1)
        self.assertEqual(second.provider_call_count, 1)

    def test_daily_quota_blocks_before_provider_action_and_records_attempt(self) -> None:
        guard = self.guard(daily_limit=2)
        provider_calls: list[str] = []
        with guard.session() as session:
            session.call("login", lambda: provider_calls.append("login"))
            session.call("query", lambda: provider_calls.append("query"))
            with self.assertRaises(BaostockQuotaExceeded):
                session.call("logout", lambda: provider_calls.append("logout"))

        self.assertEqual(provider_calls, ["login", "query"])
        usage = guard.daily_usage(date(2026, 8, 10))
        self.assertEqual(usage.provider_call_count, 2)
        self.assertEqual(usage.blocked_attempt_count, 1)
        self.assertEqual(
            [item.outcome for item in guard.attempts(date(2026, 8, 10))],
            ["completed", "completed", "quota_blocked"],
        )

    def test_calls_are_sequential_and_respect_default_minimum_interval(self) -> None:
        delays: list[float] = []

        def sleep(seconds: float) -> None:
            delays.append(seconds)
            self.clock.advance(seconds)

        guard = self.guard(minimum_interval_seconds=0.25, sleeper=sleep)
        with guard.session() as session:
            session.call("login", lambda: "ok")
            session.call("query_stock_basic", lambda: "ok")
            session.call("logout", lambda: "ok")

        self.assertEqual(delays, [0.25, 0.25])
        usage = guard.daily_usage(date(2026, 8, 10))
        self.assertEqual(usage.provider_call_count, 3)
        self.assertEqual(
            [item.operation for item in guard.attempts(date(2026, 8, 10))],
            ["login", "query_stock_basic", "logout"],
        )

    def test_blacklist_response_starts_and_repeated_signal_extends_cooldown(self) -> None:
        self.clock.value = datetime(2026, 8, 10, 8, 0, tzinfo=UTC)
        guard = self.guard(cooldown_seconds=6 * 60 * 60)
        provider_calls = 0

        def restricted() -> RestrictedResult:
            nonlocal provider_calls
            provider_calls += 1
            return RestrictedResult()

        with guard.session() as session:
            with self.assertRaises(BaostockCooldownActive):
                session.call("login", restricted)
            first_until = guard.cooldown_status().cooldown_until
            guard.record_restriction("second blacklist signal")
            second_until = guard.cooldown_status().cooldown_until
            assert first_until is not None
            assert second_until is not None
            self.assertEqual(second_until - first_until, timedelta(hours=6))

            self.clock.advance(60)
            with self.assertRaises(BaostockCooldownActive):
                session.call("query", restricted)

        self.assertEqual(provider_calls, 1)
        usage = guard.daily_usage(date(2026, 8, 10))
        self.assertEqual(usage.provider_call_count, 1)
        self.assertEqual(usage.blocked_attempt_count, 1)
        self.assertEqual(
            [item.outcome for item in guard.attempts(date(2026, 8, 10))],
            ["blacklist_restricted", "cooldown_blocked"],
        )


if __name__ == "__main__":
    unittest.main()
