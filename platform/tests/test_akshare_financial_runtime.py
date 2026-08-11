import json
import multiprocessing
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from a_share_platform.adapters.providers.akshare_financial import (
    AkShareEndpoint,
    AkShareFinancialSnapshot,
    AkShareFinancialSnapshotKey,
)
from a_share_platform.adapters.providers.akshare_financial_runtime import (
    AkShareFinancialCacheConflictError,
    AkShareFinancialCacheCorruptionError,
    AkShareFinancialGateStateError,
    ContentAddressedAkShareFinancialSnapshotCache,
    CrossProcessAkShareRequestExecutor,
)

NOW = datetime(2026, 8, 11, 2, tzinfo=UTC)


def snapshot(
    *,
    retrieved_at: datetime = NOW,
    total_assets: Decimal = Decimal(10),
) -> AkShareFinancialSnapshot:
    return AkShareFinancialSnapshot(
        key=AkShareFinancialSnapshotKey(
            provider_id="akshare",
            endpoint=AkShareEndpoint.BALANCE_SHEET,
            canonical_symbol="SH.600000",
        ),
        record_items=(
            (
                ("__a_share_platform_requested_symbol", "SH.600000"),
                ("SECURITY_CODE", "600000"),
                ("REPORT_DATE", "2024-12-31"),
                ("TOTAL_ASSETS", total_assets),
                ("OPTIONAL_PROVIDER_VALUE", None),
            ),
        ),
        retrieved_at=retrieved_at,
    )


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)


def _run_guarded_process(
    state_directory: str,
    start: object,
    ready: object,
    active: object,
    maximum_active: object,
    mutex: object,
) -> None:
    executor = CrossProcessAkShareRequestExecutor(
        state_directory=Path(state_directory),
        minimum_interval_seconds=0,
        max_attempts=1,
        retry_backoff_seconds=0,
        retryable_errors=(TimeoutError,),
    )
    ready.put("ready")  # type: ignore[attr-defined]
    start.wait(timeout=5)  # type: ignore[attr-defined]

    def action() -> str:
        with mutex:  # type: ignore[attr-defined]
            active.value += 1  # type: ignore[attr-defined]
            maximum_active.value = max(  # type: ignore[attr-defined]
                maximum_active.value,  # type: ignore[attr-defined]
                active.value,  # type: ignore[attr-defined]
            )
        time.sleep(0.15)
        with mutex:  # type: ignore[attr-defined]
            active.value -= 1  # type: ignore[attr-defined]
        return "ok"

    executor.execute("balance_sheet:SH600000", action)


class ContentAddressedAkShareFinancialSnapshotCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_round_trip_is_persistent_content_addressed_and_not_http_raw(self) -> None:
        first = ContentAddressedAkShareFinancialSnapshotCache(self.root)
        first.put(snapshot())
        first.put(snapshot())

        loaded = ContentAddressedAkShareFinancialSnapshotCache(self.root).get(snapshot().key)

        self.assertEqual(loaded, snapshot())
        assert loaded is not None
        self.assertEqual(loaded.retrieved_at, NOW)
        self.assertEqual(
            loaded.materialize()[0]["TOTAL_ASSETS"],
            Decimal(10),
        )
        objects = tuple((self.root / "objects" / "sha256").glob("*.json"))
        indexes = tuple((self.root / "indexes" / "sha256").glob("*.json"))
        self.assertEqual(len(objects), 1)
        self.assertEqual(len(indexes), 1)
        payload = json.loads(objects[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["evidence_kind"], "decoded_provider_extraction")
        self.assertFalse(payload["byte_exact_http"])

    def test_tampered_or_malformed_cache_fails_closed(self) -> None:
        cache = ContentAddressedAkShareFinancialSnapshotCache(self.root)
        cache.put(snapshot())
        content_path = next((self.root / "objects" / "sha256").glob("*.json"))
        content_path.write_bytes(b"tampered")

        with self.assertRaisesRegex(
            AkShareFinancialCacheCorruptionError,
            "hash mismatch",
        ):
            cache.get(snapshot().key)

        with tempfile.TemporaryDirectory() as directory:
            malformed = ContentAddressedAkShareFinancialSnapshotCache(Path(directory))
            malformed.put(snapshot())
            index_path = next((Path(directory) / "indexes" / "sha256").glob("*.json"))
            index_path.write_bytes(b"{")
            with self.assertRaises(AkShareFinancialCacheCorruptionError):
                malformed.get(snapshot().key)

    def test_same_key_cannot_be_silently_rebound_to_new_content(self) -> None:
        cache = ContentAddressedAkShareFinancialSnapshotCache(self.root)
        cache.put(snapshot())

        with self.assertRaisesRegex(
            AkShareFinancialCacheConflictError,
            "immutable cache key",
        ):
            cache.put(
                snapshot(
                    retrieved_at=NOW + timedelta(seconds=1),
                    total_assets=Decimal(11),
                )
            )

        self.assertEqual(cache.get(snapshot().key), snapshot())

    def test_failed_atomic_publish_leaves_no_visible_index_or_temp_file(self) -> None:
        cache = ContentAddressedAkShareFinancialSnapshotCache(self.root)
        with (
            patch(
                "a_share_platform.adapters.providers.akshare_financial_runtime.os.replace",
                side_effect=OSError("disk failure"),
            ),
            self.assertRaisesRegex(OSError, "disk failure"),
        ):
            cache.put(snapshot())

        self.assertEqual(
            tuple((self.root / "indexes" / "sha256").glob("*.json")),
            (),
        )
        self.assertEqual(tuple(self.root.rglob("*.tmp")), ())


class CrossProcessAkShareRequestExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state_directory = Path(self.temp.name)

    def executor(self, clock: MutableClock, sleeps: list[float]):
        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            clock.advance(seconds)

        return CrossProcessAkShareRequestExecutor(
            state_directory=self.state_directory,
            minimum_interval_seconds=1,
            max_attempts=2,
            retry_backoff_seconds=0.25,
            clock=clock,
            sleeper=sleep,
            retryable_errors=(TimeoutError,),
        )

    def test_minimum_interval_is_shared_by_distinct_executor_instances(self) -> None:
        clock = MutableClock(NOW)
        sleeps: list[float] = []
        starts: list[datetime] = []
        self.executor(clock, sleeps).execute(
            "balance_sheet:SH600000",
            lambda: starts.append(clock()) or "first",
        )
        second = self.executor(clock, sleeps).execute(
            "balance_sheet:SH600001",
            lambda: starts.append(clock()) or "second",
        )

        self.assertEqual(second, "second")
        self.assertEqual(starts, [NOW, NOW + timedelta(seconds=1)])
        self.assertEqual(sleeps, [1.0])

    def test_retry_is_bounded_and_every_attempt_obeys_global_interval(self) -> None:
        clock = MutableClock(NOW)
        sleeps: list[float] = []
        attempts = 0

        def flaky() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise TimeoutError("temporary")
            return "ok"

        result = self.executor(clock, sleeps).execute("income:SH600000", flaky)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts, 2)
        self.assertEqual(sleeps, [0.25, 0.75])

    def test_corrupt_gate_state_blocks_before_provider_action(self) -> None:
        (self.state_directory / "request-state.json").write_bytes(b"{")
        clock = MutableClock(NOW)
        called = False

        def action() -> None:
            nonlocal called
            called = True

        with self.assertRaises(AkShareFinancialGateStateError):
            self.executor(clock, []).execute("cash_flow:SH600000", action)
        self.assertFalse(called)

    def test_only_one_provider_action_runs_across_processes(self) -> None:
        context = multiprocessing.get_context("spawn")
        start = context.Event()
        ready = context.Queue()
        active = context.Value("i", 0)
        maximum_active = context.Value("i", 0)
        mutex = context.Lock()
        processes = [
            context.Process(
                target=_run_guarded_process,
                args=(
                    str(self.state_directory),
                    start,
                    ready,
                    active,
                    maximum_active,
                    mutex,
                ),
            )
            for _item in range(2)
        ]
        for process in processes:
            process.start()
        self.assertEqual({ready.get(timeout=5), ready.get(timeout=5)}, {"ready"})
        start.set()
        for process in processes:
            process.join(timeout=10)

        self.assertTrue(all(not process.is_alive() for process in processes))
        self.assertTrue(all(process.exitcode == 0 for process in processes))
        self.assertEqual(maximum_active.value, 1)


if __name__ == "__main__":
    unittest.main()
