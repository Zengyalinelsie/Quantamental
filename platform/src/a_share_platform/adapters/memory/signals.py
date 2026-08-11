"""In-memory contract and unavailable adapters for SignalSnapshot storage."""

from __future__ import annotations

from datetime import datetime
from typing import Never

from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.signals import SignalSnapshot
from a_share_platform.ports.signals import (
    SignalSnapshotLedgerConflict,
    SignalSnapshotLedgerUnavailable,
)

SignalSnapshotNaturalKey = tuple[str, str, datetime, int, ApprovalScope]


def _natural_key(value: SignalSnapshot) -> SignalSnapshotNaturalKey:
    return (
        value.universe_version_id,
        value.security_id,
        value.decision_time,
        value.horizon_trading_days,
        value.approval_scope,
    )


class InMemorySignalSnapshotRepository:
    """Append-only adapter intended for contract tests, never runtime fixtures."""

    def __init__(self) -> None:
        self._snapshots: dict[str, SignalSnapshot] = {}
        self._snapshot_id_by_natural_key: dict[SignalSnapshotNaturalKey, str] = {}

    def append_snapshot(self, value: SignalSnapshot) -> SignalSnapshot:
        if not isinstance(value, SignalSnapshot):
            raise TypeError("value must be a SignalSnapshot")
        existing = self._snapshots.get(value.snapshot_id)
        if existing is not None:
            if existing.content_hash != value.content_hash:
                raise SignalSnapshotLedgerConflict(
                    f"immutable snapshot_id conflict: {value.snapshot_id}"
                )
            return existing
        natural_key = _natural_key(value)
        prior_id = self._snapshot_id_by_natural_key.get(natural_key)
        if prior_id is not None:
            raise SignalSnapshotLedgerConflict(
                "SignalSnapshot natural key is immutable; "
                f"existing={prior_id}; attempted={value.snapshot_id}"
            )
        self._snapshots[value.snapshot_id] = value
        self._snapshot_id_by_natural_key[natural_key] = value.snapshot_id
        return value

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]:
        return tuple(self._snapshots[key] for key in sorted(self._snapshots))


class UnavailableSignalSnapshotRepository:
    """Fail closed rather than populate runtime snapshots when storage is absent."""

    def __init__(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("unavailable SignalSnapshot store reason must not be empty")
        self._reason = reason

    def _raise(self) -> Never:
        raise SignalSnapshotLedgerUnavailable(self._reason)

    def append_snapshot(self, value: SignalSnapshot) -> SignalSnapshot:
        del value
        self._raise()

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None:
        del snapshot_id
        self._raise()

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]:
        self._raise()


__all__ = [
    "InMemorySignalSnapshotRepository",
    "UnavailableSignalSnapshotRepository",
]
