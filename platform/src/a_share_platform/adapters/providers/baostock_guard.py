"""Cross-process BaoStock session, quota, pacing, and cooldown guard."""

from __future__ import annotations

import fcntl
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self, TextIO, TypeVar
from zoneinfo import ZoneInfo

_T = TypeVar("_T")
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_BLACKLIST_MARKERS = (
    "blacklist",
    "too frequent",
    "access restricted",
    "access limit",
    "黑名单",
    "访问限制",
    "访问频繁",
    "请求频繁",
    "操作频繁",
)
DEFAULT_BAOSTOCK_GUARD_DIRECTORY = (
    Path(__file__).resolve().parents[4] / "var" / "private-research" / "baostock-guard"
)


class BaostockGuardError(RuntimeError):
    """Base class for local BaoStock safety-gate failures."""


class BaostockSessionBusy(BaostockGuardError):
    """Raised when another process already owns the global BaoStock session."""


class BaostockQuotaExceeded(BaostockGuardError):
    """Raised before a provider call would exceed the platform daily allowance."""


class BaostockCooldownActive(BaostockGuardError):
    """Raised while a provider restriction cooldown is active."""


@dataclass(frozen=True)
class BaostockDailyUsage:
    shanghai_day: date
    provider_call_count: int
    blocked_attempt_count: int


@dataclass(frozen=True)
class BaostockCallAttempt:
    attempt_id: int
    attempted_at: datetime
    shanghai_day: date
    operation: str
    outcome: str
    reason: str | None


@dataclass(frozen=True)
class BaostockCooldownStatus:
    cooldown_until: datetime | None
    reason: str | None


class BaostockSession:
    """One globally exclusive SDK session with sequential guarded calls."""

    def __init__(
        self,
        guard: BaostockGuard,
        process_lock: threading.Lock,
        lock_file: TextIO,
    ) -> None:
        self._guard = guard
        self._process_lock = process_lock
        self._lock_file = lock_file
        self._call_lock = threading.Lock()
        self._entered = False
        self._closed = False

    def __enter__(self) -> Self:
        if self._closed:
            raise BaostockGuardError("BaoStock session cannot be reused after close")
        self._entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        with self._call_lock:
            self._guard._release_session(self._process_lock, self._lock_file)
            self._closed = True

    def call(self, operation: str, action: Callable[[], _T]) -> _T:
        if not self._entered or self._closed:
            raise BaostockGuardError("BaoStock call requires an active guarded session")
        if not operation.strip():
            raise ValueError("operation must not be empty")
        if not callable(action):
            raise TypeError("action must be callable")
        with self._call_lock:
            return self._guard._invoke(operation.strip(), action)


class BaostockGuard:
    """Fail-closed local guard for all BaoStock SDK attempts.

    A filesystem lock represents process liveness. Database ingestion status is
    deliberately not consulted, so a stale ``running`` checkpoint cannot block
    a session after its owning process has exited.
    """

    _registry_lock = threading.Lock()
    _process_locks: ClassVar[dict[Path, threading.Lock]] = {}

    def __init__(
        self,
        *,
        state_directory: Path = DEFAULT_BAOSTOCK_GUARD_DIRECTORY,
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        daily_limit: int = 40_000,
        minimum_interval_seconds: float = 0.25,
        cooldown_seconds: float = 6 * 60 * 60,
    ) -> None:
        if type(daily_limit) is not int or not 1 <= daily_limit <= 40_000:
            raise ValueError("daily_limit must be an integer in [1, 40000]")
        if minimum_interval_seconds < 0:
            raise ValueError("minimum_interval_seconds cannot be negative")
        if cooldown_seconds < 6 * 60 * 60:
            raise ValueError("cooldown_seconds must be at least six hours")
        self._state_directory = Path(state_directory).resolve(strict=False)
        self._state_directory.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._state_directory / "session.lock"
        self._ledger_path = self._state_directory / "usage.sqlite3"
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper
        self._daily_limit = daily_limit
        self._minimum_interval_seconds = float(minimum_interval_seconds)
        self._cooldown = timedelta(seconds=float(cooldown_seconds))
        self._initialize_ledger()

    def session(self) -> BaostockSession:
        process_lock = self._process_lock(self._lock_path)
        if not process_lock.acquire(blocking=False):
            raise BaostockSessionBusy("another local BaoStock session is active")
        descriptor: int | None = None
        lock_file: TextIO | None = None
        try:
            descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
            lock_file = os.fdopen(descriptor, "r+")
            descriptor = None
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as error:
            if lock_file is not None:
                lock_file.close()
            elif descriptor is not None:
                os.close(descriptor)
            process_lock.release()
            raise BaostockSessionBusy(
                "another process already owns the global BaoStock session"
            ) from error
        assert lock_file is not None
        return BaostockSession(self, process_lock, lock_file)

    def daily_usage(self, shanghai_day: date) -> BaostockDailyUsage:
        if not isinstance(shanghai_day, date):
            raise TypeError("shanghai_day must be a date")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT provider_call_count, blocked_attempt_count
                FROM baostock_daily_usage
                WHERE shanghai_day = ?
                """,
                (shanghai_day.isoformat(),),
            ).fetchone()
        return BaostockDailyUsage(
            shanghai_day=shanghai_day,
            provider_call_count=0 if row is None else int(row[0]),
            blocked_attempt_count=0 if row is None else int(row[1]),
        )

    def attempts(self, shanghai_day: date) -> tuple[BaostockCallAttempt, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT attempt_id, attempted_at, shanghai_day, operation, outcome, reason
                FROM baostock_call_attempts
                WHERE shanghai_day = ?
                ORDER BY attempt_id
                """,
                (shanghai_day.isoformat(),),
            ).fetchall()
        return tuple(
            BaostockCallAttempt(
                attempt_id=int(row[0]),
                attempted_at=datetime.fromisoformat(str(row[1])),
                shanghai_day=date.fromisoformat(str(row[2])),
                operation=str(row[3]),
                outcome=str(row[4]),
                reason=None if row[5] is None else str(row[5]),
            )
            for row in rows
        )

    def cooldown_status(self) -> BaostockCooldownStatus:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT cooldown_until, cooldown_reason
                FROM baostock_guard_state
                WHERE singleton = 1
                """
            ).fetchone()
        if row is None or row[0] is None:
            return BaostockCooldownStatus(None, None)
        return BaostockCooldownStatus(
            datetime.fromisoformat(str(row[0])),
            None if row[1] is None else str(row[1]),
        )

    def record_restriction(self, reason: str) -> BaostockCooldownStatus:
        return self._record_restriction(reason, attempt_id=None)

    @classmethod
    def _process_lock(cls, path: Path) -> threading.Lock:
        with cls._registry_lock:
            return cls._process_locks.setdefault(path, threading.Lock())

    @staticmethod
    def _release_session(process_lock: threading.Lock, lock_file: TextIO) -> None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()
            process_lock.release()

    def _invoke(self, operation: str, action: Callable[[], _T]) -> _T:
        self._wait_for_minimum_interval()
        attempt_id = self._reserve_attempt(operation)
        try:
            value = action()
        except BaseException as error:
            reason = str(error).strip() or type(error).__name__
            if self._is_restriction(reason):
                status = self._record_restriction(reason, attempt_id=attempt_id)
                raise self._cooldown_error(status) from error
            self._complete_attempt(attempt_id, "provider_error", reason)
            raise
        restriction = self._restriction_reason(value)
        if restriction is not None:
            status = self._record_restriction(restriction, attempt_id=attempt_id)
            raise self._cooldown_error(status)
        self._complete_attempt(attempt_id, "completed", None)
        return value

    def _wait_for_minimum_interval(self) -> None:
        if self._minimum_interval_seconds == 0:
            return
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT attempted_at
                FROM baostock_call_attempts
                WHERE outcome NOT IN ('quota_blocked', 'cooldown_blocked')
                ORDER BY attempt_id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return
        last_attempt = datetime.fromisoformat(str(row[0]))
        wait_seconds = (
            last_attempt
            + timedelta(seconds=self._minimum_interval_seconds)
            - self._now()
        ).total_seconds()
        if wait_seconds > 0:
            self._sleeper(wait_seconds)

    def _reserve_attempt(self, operation: str) -> int:
        now = self._now()
        shanghai_day = now.astimezone(_SHANGHAI).date()
        connection = self._connect()
        blocked_error: BaostockGuardError | None = None
        attempt_id: int | None = None
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO baostock_daily_usage (
                    shanghai_day, provider_call_count, blocked_attempt_count, updated_at
                ) VALUES (?, 0, 0, ?)
                """,
                (shanghai_day.isoformat(), now.isoformat()),
            )
            state = connection.execute(
                """
                SELECT cooldown_until, cooldown_reason
                FROM baostock_guard_state
                WHERE singleton = 1
                """
            ).fetchone()
            cooldown_until = (
                None
                if state is None or state[0] is None
                else datetime.fromisoformat(str(state[0]))
            )
            if cooldown_until is not None and cooldown_until > now:
                reason = None if state is None or state[1] is None else str(state[1])
                attempt_id = self._insert_attempt(
                    connection,
                    now,
                    shanghai_day,
                    operation,
                    "cooldown_blocked",
                    reason,
                )
                self._increment_blocked(connection, shanghai_day, now)
                blocked_error = self._cooldown_error(
                    BaostockCooldownStatus(cooldown_until, reason)
                )
            else:
                usage = connection.execute(
                    """
                    SELECT provider_call_count
                    FROM baostock_daily_usage
                    WHERE shanghai_day = ?
                    """,
                    (shanghai_day.isoformat(),),
                ).fetchone()
                assert usage is not None
                if int(usage[0]) >= self._daily_limit:
                    reason = f"daily provider call limit {self._daily_limit} reached"
                    attempt_id = self._insert_attempt(
                        connection,
                        now,
                        shanghai_day,
                        operation,
                        "quota_blocked",
                        reason,
                    )
                    self._increment_blocked(connection, shanghai_day, now)
                    blocked_error = BaostockQuotaExceeded(reason)
                else:
                    connection.execute(
                        """
                        UPDATE baostock_daily_usage
                        SET provider_call_count = provider_call_count + 1,
                            updated_at = ?
                        WHERE shanghai_day = ?
                        """,
                        (now.isoformat(), shanghai_day.isoformat()),
                    )
                    attempt_id = self._insert_attempt(
                        connection,
                        now,
                        shanghai_day,
                        operation,
                        "reserved",
                        None,
                    )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        if blocked_error is not None:
            raise blocked_error
        assert attempt_id is not None
        return attempt_id

    @staticmethod
    def _insert_attempt(
        connection: sqlite3.Connection,
        now: datetime,
        shanghai_day: date,
        operation: str,
        outcome: str,
        reason: str | None,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO baostock_call_attempts (
                attempted_at, shanghai_day, operation, outcome, reason
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (now.isoformat(), shanghai_day.isoformat(), operation, outcome, reason),
        )
        assert cursor.lastrowid is not None
        return int(cursor.lastrowid)

    @staticmethod
    def _increment_blocked(
        connection: sqlite3.Connection,
        shanghai_day: date,
        now: datetime,
    ) -> None:
        connection.execute(
            """
            UPDATE baostock_daily_usage
            SET blocked_attempt_count = blocked_attempt_count + 1,
                updated_at = ?
            WHERE shanghai_day = ?
            """,
            (now.isoformat(), shanghai_day.isoformat()),
        )

    def _complete_attempt(
        self,
        attempt_id: int,
        outcome: str,
        reason: str | None,
    ) -> None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE baostock_call_attempts
                SET outcome = ?, reason = ?
                WHERE attempt_id = ? AND outcome = 'reserved'
                """,
                (outcome, reason, attempt_id),
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _record_restriction(
        self,
        reason: str,
        *,
        attempt_id: int | None,
    ) -> BaostockCooldownStatus:
        text = reason.strip()
        if not text:
            raise ValueError("restriction reason must not be empty")
        now = self._now()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT cooldown_until FROM baostock_guard_state WHERE singleton = 1"
            ).fetchone()
            previous = (
                None if row is None or row[0] is None else datetime.fromisoformat(str(row[0]))
            )
            base = now if previous is None or previous < now else previous
            cooldown_until = base + self._cooldown
            connection.execute(
                """
                INSERT INTO baostock_guard_state (
                    singleton, cooldown_until, cooldown_reason, updated_at
                ) VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    cooldown_until = excluded.cooldown_until,
                    cooldown_reason = excluded.cooldown_reason,
                    updated_at = excluded.updated_at
                """,
                (cooldown_until.isoformat(), text, now.isoformat()),
            )
            if attempt_id is not None:
                connection.execute(
                    """
                    UPDATE baostock_call_attempts
                    SET outcome = 'blacklist_restricted', reason = ?
                    WHERE attempt_id = ? AND outcome = 'reserved'
                    """,
                    (text, attempt_id),
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return BaostockCooldownStatus(cooldown_until, text)

    @staticmethod
    def _cooldown_error(status: BaostockCooldownStatus) -> BaostockCooldownActive:
        return BaostockCooldownActive(
            "BaoStock provider cooldown is active until "
            f"{status.cooldown_until.isoformat() if status.cooldown_until else 'unknown'}; "
            f"reason={status.reason or 'provider restriction'}"
        )

    @classmethod
    def _restriction_reason(cls, value: object) -> str | None:
        message = str(getattr(value, "error_msg", "")).strip()
        if cls._is_restriction(message):
            code = str(getattr(value, "error_code", "")).strip()
            return f"error_code={code or 'unknown'}; error_msg={message}"
        return None

    @staticmethod
    def _is_restriction(message: str) -> bool:
        normalized = message.casefold()
        return any(marker in normalized for marker in _BLACKLIST_MARKERS)

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("BaoStock guard clock must be timezone-aware")
        return value.astimezone(UTC)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._ledger_path, timeout=5)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_ledger(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS baostock_daily_usage (
                    shanghai_day TEXT PRIMARY KEY,
                    provider_call_count INTEGER NOT NULL CHECK (provider_call_count >= 0),
                    blocked_attempt_count INTEGER NOT NULL CHECK (blocked_attempt_count >= 0),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS baostock_guard_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    cooldown_until TEXT,
                    cooldown_reason TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS baostock_call_attempts (
                    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempted_at TEXT NOT NULL,
                    shanghai_day TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reason TEXT
                );

                CREATE INDEX IF NOT EXISTS ix_baostock_attempts_day
                ON baostock_call_attempts (shanghai_day, attempt_id);
                """
            )
