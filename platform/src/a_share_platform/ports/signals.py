"""Persistence port for immutable, approval-scoped SignalSnapshots."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.signals import SignalSnapshot


class SignalSnapshotLedgerConflict(RuntimeError):
    """An immutable snapshot identifier or natural key was reused."""


class SignalSnapshotLedgerUnavailable(RuntimeError):
    """The durable SignalSnapshot ledger is unavailable or unconfigured."""


class SignalSnapshotRepository(Protocol):
    def append_snapshot(self, value: SignalSnapshot) -> SignalSnapshot: ...

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None: ...

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]: ...


__all__ = [
    "SignalSnapshotLedgerConflict",
    "SignalSnapshotLedgerUnavailable",
    "SignalSnapshotRepository",
]
