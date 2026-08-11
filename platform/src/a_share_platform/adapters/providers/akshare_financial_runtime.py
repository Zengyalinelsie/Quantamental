"""Private-local persistent cache and provider-call gate for AkShare financials.

The cache stores deterministic serialization of decoded DataFrame records.  It
is intentionally labelled as provider extraction rather than byte-exact HTTP
evidence and cannot raise the trust ceiling above ``normalized_current``.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar, TypeVar

from a_share_platform.adapters.providers.akshare_financial import (
    AkShareEndpoint,
    AkShareFinancialSnapshot,
    AkShareFinancialSnapshotCache,
    AkShareFinancialSnapshotKey,
)

_T = TypeVar("_T")
_CACHE_SCHEMA = "akshare-provider-extraction-cache:v1"
_INDEX_SCHEMA = "akshare-provider-extraction-index:v1"
_GATE_SCHEMA = "akshare-provider-request-gate:v1"
_EVIDENCE_KIND = "decoded_provider_extraction"
_RUNTIME_ROOT = (
    Path(__file__).resolve().parents[4] / "var" / "private-research" / "akshare-financial"
)
DEFAULT_AKSHARE_FINANCIAL_CACHE_DIRECTORY = _RUNTIME_ROOT / "cache"
DEFAULT_AKSHARE_FINANCIAL_GATE_DIRECTORY = _RUNTIME_ROOT / "gate"


class AkShareFinancialCacheError(RuntimeError):
    """Base class for fail-closed persistent extraction-cache errors."""


class AkShareFinancialCacheCorruptionError(AkShareFinancialCacheError):
    """Raised when an index, payload, or content hash cannot be trusted."""


class AkShareFinancialCacheConflictError(AkShareFinancialCacheError):
    """Raised when an immutable source key is rebound to different content."""


class AkShareFinancialGateStateError(RuntimeError):
    """Raised before provider access when persisted pacing state is invalid."""


class _PathLocks:
    _registry_guard = threading.Lock()
    _locks: ClassVar[dict[Path, threading.RLock]] = {}

    @classmethod
    def for_path(cls, path: Path) -> threading.RLock:
        with cls._registry_guard:
            return cls._locks.setdefault(path, threading.RLock())


@contextmanager
def _file_lock(path: Path, operation: int) -> Iterator[None]:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    process_lock = _PathLocks.for_path(path)
    with process_lock:
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        lock_file = os.fdopen(descriptor, "r+")
        try:
            fcntl.flock(lock_file.fileno(), operation)
            yield
        finally:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            finally:
                lock_file.close()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _key_value(key: AkShareFinancialSnapshotKey) -> dict[str, str]:
    return {
        "canonical_symbol": key.canonical_symbol,
        "endpoint": key.endpoint.value,
        "provider_id": key.provider_id,
    }


def _encode_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("cached Decimal values must be finite")
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("cached float values must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("provider extraction cache only accepts immutable scalar values")


def _decode_scalar(value: object) -> object:
    if isinstance(value, dict):
        if set(value) != {"type", "value"} or value.get("type") != "decimal":
            raise ValueError("unknown tagged provider scalar")
        decimal_text = value.get("value")
        if not isinstance(decimal_text, str):
            raise TypeError("tagged Decimal value must be text")
        result = Decimal(decimal_text)
        if not result.is_finite():
            raise ValueError("cached Decimal values must be finite")
        return result
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("cached float values must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("unknown provider scalar encoding")


def _snapshot_payload(snapshot: AkShareFinancialSnapshot) -> dict[str, object]:
    return {
        "byte_exact_http": False,
        "evidence_kind": _EVIDENCE_KIND,
        "key": _key_value(snapshot.key),
        "records": [
            [{"field": field, "value": _encode_scalar(value)} for field, value in record]
            for record in snapshot.record_items
        ],
        "retrieved_at": snapshot.retrieved_at.isoformat(),
        "schema": _CACHE_SCHEMA,
    }


class ContentAddressedAkShareFinancialSnapshotCache(AkShareFinancialSnapshotCache):
    """Persistent immutable index over content-addressed decoded extractions.

    Use a run-scoped root when a later run must deliberately refresh current
    provider observations.  A key inside one root is immutable by design.
    """

    def __init__(
        self,
        root: Path = DEFAULT_AKSHARE_FINANCIAL_CACHE_DIRECTORY,
    ) -> None:
        self._root = Path(root).resolve(strict=False)
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock_path = self._root / "cache.lock"

    def get(
        self,
        key: AkShareFinancialSnapshotKey,
    ) -> AkShareFinancialSnapshot | None:
        self._require_key(key)
        with _file_lock(self._lock_path, fcntl.LOCK_SH):
            return self._read_locked(key)

    def put(self, snapshot: AkShareFinancialSnapshot) -> None:
        if not isinstance(snapshot, AkShareFinancialSnapshot):
            raise TypeError("snapshot must be an AkShareFinancialSnapshot")
        payload = _canonical_json(_snapshot_payload(snapshot))
        digest = hashlib.sha256(payload).hexdigest()
        content_path = self._content_path(digest)
        index_path = self._index_path(snapshot.key)
        manifest = _canonical_json(
            {
                "content_sha256": digest,
                "key": _key_value(snapshot.key),
                "schema": _INDEX_SCHEMA,
            }
        )
        with _file_lock(self._lock_path, fcntl.LOCK_EX):
            self._ensure_content(content_path, payload, digest)
            existing = self._read_locked(snapshot.key)
            if existing is not None:
                if existing != snapshot:
                    raise AkShareFinancialCacheConflictError(
                        "immutable cache key already references different content"
                    )
                return
            _atomic_write(index_path, manifest)

    @staticmethod
    def _require_key(key: AkShareFinancialSnapshotKey) -> None:
        if not isinstance(key, AkShareFinancialSnapshotKey):
            raise TypeError("key must be an AkShareFinancialSnapshotKey")

    def _index_path(self, key: AkShareFinancialSnapshotKey) -> Path:
        key_digest = hashlib.sha256(_canonical_json(_key_value(key))).hexdigest()
        return self._root / "indexes" / "sha256" / f"{key_digest}.json"

    def _content_path(self, digest: str) -> Path:
        return self._root / "objects" / "sha256" / f"{digest}.json"

    @staticmethod
    def _ensure_content(path: Path, payload: bytes, digest: str) -> None:
        if path.exists():
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest or existing != payload:
                raise AkShareFinancialCacheCorruptionError(
                    "content-addressed provider extraction mismatch"
                )
            return
        _atomic_write(path, payload)

    def _read_locked(
        self,
        key: AkShareFinancialSnapshotKey,
    ) -> AkShareFinancialSnapshot | None:
        index_path = self._index_path(key)
        if not index_path.exists():
            return None
        manifest = self._json_object(index_path, "cache index")
        if set(manifest) != {"content_sha256", "key", "schema"}:
            raise AkShareFinancialCacheCorruptionError("cache index fields are invalid")
        if manifest.get("schema") != _INDEX_SCHEMA:
            raise AkShareFinancialCacheCorruptionError("cache index schema is invalid")
        if manifest.get("key") != _key_value(key):
            raise AkShareFinancialCacheCorruptionError("cache index key mismatch")
        digest = manifest.get("content_sha256")
        if not self._valid_digest(digest):
            raise AkShareFinancialCacheCorruptionError("cache content digest is invalid")
        assert isinstance(digest, str)
        content_path = self._content_path(digest)
        if not content_path.is_file():
            raise AkShareFinancialCacheCorruptionError("cache content object is missing")
        payload_bytes = content_path.read_bytes()
        if hashlib.sha256(payload_bytes).hexdigest() != digest:
            raise AkShareFinancialCacheCorruptionError("cache content hash mismatch")
        payload = self._decode_json(payload_bytes, "cache content")
        snapshot = self._decode_snapshot(payload)
        if snapshot.key != key:
            raise AkShareFinancialCacheCorruptionError("cache payload key mismatch")
        return snapshot

    @staticmethod
    def _valid_digest(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and all(character in "0123456789abcdef" for character in value)
        )

    @classmethod
    def _json_object(cls, path: Path, label: str) -> Mapping[str, object]:
        return cls._decode_json(path.read_bytes(), label)

    @staticmethod
    def _decode_json(payload: bytes, label: str) -> Mapping[str, object]:
        try:
            value = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AkShareFinancialCacheCorruptionError(f"{label} is not valid JSON") from error
        if not isinstance(value, dict):
            raise AkShareFinancialCacheCorruptionError(f"{label} must contain a JSON object")
        return value

    @staticmethod
    def _decode_snapshot(payload: Mapping[str, object]) -> AkShareFinancialSnapshot:
        try:
            if set(payload) != {
                "byte_exact_http",
                "evidence_kind",
                "key",
                "records",
                "retrieved_at",
                "schema",
            }:
                raise ValueError("cache payload fields are invalid")
            if payload["schema"] != _CACHE_SCHEMA:
                raise ValueError("cache payload schema is invalid")
            if payload["evidence_kind"] != _EVIDENCE_KIND:
                raise ValueError("cache evidence kind is invalid")
            if payload["byte_exact_http"] is not False:
                raise ValueError("cache cannot claim byte-exact HTTP evidence")
            key_value = payload["key"]
            if not isinstance(key_value, dict) or set(key_value) != {
                "canonical_symbol",
                "endpoint",
                "provider_id",
            }:
                raise TypeError("cache payload key is invalid")
            key = AkShareFinancialSnapshotKey(
                provider_id=str(key_value["provider_id"]),
                endpoint=AkShareEndpoint(str(key_value["endpoint"])),
                canonical_symbol=str(key_value["canonical_symbol"]),
            )
            encoded_records = payload["records"]
            if not isinstance(encoded_records, list):
                raise TypeError("cache payload records must be a list")
            records: list[tuple[tuple[str, object], ...]] = []
            for encoded_record in encoded_records:
                if not isinstance(encoded_record, list):
                    raise TypeError("cache payload record must be a list")
                record: list[tuple[str, object]] = []
                for encoded_field in encoded_record:
                    if not isinstance(encoded_field, dict) or set(encoded_field) != {
                        "field",
                        "value",
                    }:
                        raise TypeError("cache payload field is invalid")
                    field = encoded_field["field"]
                    if not isinstance(field, str):
                        raise TypeError("cache provider field must be text")
                    record.append((field, _decode_scalar(encoded_field["value"])))
                records.append(tuple(record))
            retrieved_at_text = payload["retrieved_at"]
            if not isinstance(retrieved_at_text, str):
                raise TypeError("cache retrieved_at must be text")
            return AkShareFinancialSnapshot(
                key=key,
                record_items=tuple(records),
                retrieved_at=datetime.fromisoformat(retrieved_at_text),
            )
        except (
            InvalidOperation,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            raise AkShareFinancialCacheCorruptionError(
                f"invalid provider extraction cache payload: {error}"
            ) from error


class CrossProcessAkShareRequestExecutor:
    """One global provider call at a time with persisted start-to-start pacing."""

    def __init__(
        self,
        *,
        state_directory: Path = DEFAULT_AKSHARE_FINANCIAL_GATE_DIRECTORY,
        minimum_interval_seconds: float,
        max_attempts: int,
        retry_backoff_seconds: float,
        retryable_errors: tuple[type[Exception], ...],
        clock: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        for value, name in (
            (minimum_interval_seconds, "minimum_interval_seconds"),
            (retry_backoff_seconds, "retry_backoff_seconds"),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if type(max_attempts) is not int or max_attempts <= 0:
            raise ValueError("max_attempts must be a positive integer")
        if not retryable_errors or any(
            not isinstance(error, type) or not issubclass(error, Exception)
            for error in retryable_errors
        ):
            raise ValueError("retryable_errors must contain Exception types")
        self._state_directory = Path(state_directory).resolve(strict=False)
        self._state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._lock_path = self._state_directory / "request.lock"
        self._state_path = self._state_directory / "request-state.json"
        self._minimum_interval = timedelta(seconds=float(minimum_interval_seconds))
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = float(retry_backoff_seconds)
        self._retryable_errors = retryable_errors
        self._clock = clock or (lambda: datetime.now(UTC))
        self._sleeper = sleeper

    def execute(self, operation: str, action: Callable[[], _T]) -> _T:
        if not isinstance(operation, str) or not operation.strip():
            raise ValueError("operation must not be empty")
        if not callable(action):
            raise TypeError("action must be callable")
        with _file_lock(self._lock_path, fcntl.LOCK_EX):
            attempt = 0
            while True:
                self._wait_and_record_start(operation.strip())
                attempt += 1
                try:
                    return action()
                except self._retryable_errors:
                    if attempt >= self._max_attempts:
                        raise
                    self._sleeper(self._retry_backoff_seconds * attempt)

    def _wait_and_record_start(self, operation: str) -> None:
        previous = self._read_last_started_at()
        now = self._now()
        if previous is not None:
            if now < previous:
                raise AkShareFinancialGateStateError(
                    "local clock precedes persisted provider request state"
                )
            eligible_at = previous + self._minimum_interval
            wait_seconds = (eligible_at - now).total_seconds()
            if wait_seconds > 0:
                self._sleeper(wait_seconds)
                now = self._now()
                if now < eligible_at:
                    raise AkShareFinancialGateStateError(
                        "provider request sleeper returned before the global interval elapsed"
                    )
        _atomic_write(
            self._state_path,
            _canonical_json(
                {
                    "last_operation": operation,
                    "last_started_at": now.isoformat(),
                    "schema": _GATE_SCHEMA,
                }
            ),
        )

    def _read_last_started_at(self) -> datetime | None:
        if not self._state_path.exists():
            return None
        try:
            value = json.loads(self._state_path.read_bytes())
            if not isinstance(value, dict) or set(value) != {
                "last_operation",
                "last_started_at",
                "schema",
            }:
                raise ValueError("provider gate state fields are invalid")
            if value["schema"] != _GATE_SCHEMA:
                raise ValueError("provider gate state schema is invalid")
            if not isinstance(value["last_operation"], str) or not value["last_operation"].strip():
                raise ValueError("provider gate operation is invalid")
            timestamp = value["last_started_at"]
            if not isinstance(timestamp, str):
                raise TypeError("provider gate timestamp must be text")
            result = datetime.fromisoformat(timestamp)
            if result.tzinfo is None or result.utcoffset() is None:
                raise ValueError("provider gate timestamp must be timezone-aware")
            return result.astimezone(UTC)
        except (
            json.JSONDecodeError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ) as error:
            raise AkShareFinancialGateStateError(
                f"invalid persisted provider request state: {error}"
            ) from error

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider request clock must be timezone-aware")
        return value.astimezone(UTC)


__all__ = [
    "DEFAULT_AKSHARE_FINANCIAL_CACHE_DIRECTORY",
    "DEFAULT_AKSHARE_FINANCIAL_GATE_DIRECTORY",
    "AkShareFinancialCacheConflictError",
    "AkShareFinancialCacheCorruptionError",
    "AkShareFinancialCacheError",
    "AkShareFinancialGateStateError",
    "ContentAddressedAkShareFinancialSnapshotCache",
    "CrossProcessAkShareRequestExecutor",
]
