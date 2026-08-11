"""Append and separately query research versus forward SignalSnapshots."""

from __future__ import annotations

from a_share_platform.domain.factor_lifecycle import ApprovalScope
from a_share_platform.domain.signals import SignalSnapshot
from a_share_platform.ports.signals import SignalSnapshotRepository

_PRODUCTION_SCOPES = frozenset(
    {
        ApprovalScope.SHADOW,
        ApprovalScope.PAPER,
        ApprovalScope.LIMITED_LIVE,
    }
)


class SignalSnapshotQuerySurfaceDenied(PermissionError):
    """A snapshot was requested through a surface for a different approval scope."""


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


class SignalSnapshotLedgerService:
    def __init__(self, repository: SignalSnapshotRepository) -> None:
        self._repository = repository

    def record_snapshot(self, value: SignalSnapshot) -> SignalSnapshot:
        if not isinstance(value, SignalSnapshot):
            raise TypeError("value must be a SignalSnapshot")
        return self._repository.append_snapshot(value)

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None:
        return self._repository.get_snapshot(_identifier(snapshot_id, "snapshot_id"))

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]:
        return self._repository.list_snapshots()


class ResearchSignalSnapshotQueryService:
    """Research surface: it can only read research_backtest snapshots."""

    def __init__(self, repository: SignalSnapshotRepository) -> None:
        self._repository = repository

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None:
        value = self._repository.get_snapshot(_identifier(snapshot_id, "snapshot_id"))
        if value is not None and value.approval_scope is not ApprovalScope.RESEARCH_BACKTEST:
            raise SignalSnapshotQuerySurfaceDenied(
                "research signal query cannot read a forward-approved snapshot"
            )
        return value

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]:
        return tuple(
            value
            for value in self._repository.list_snapshots()
            if value.approval_scope is ApprovalScope.RESEARCH_BACKTEST
        )


class ProductionSignalSnapshotQueryService:
    """Forward surface bound to one exact Shadow, Paper, or Limited Live scope."""

    def __init__(
        self,
        repository: SignalSnapshotRepository,
        approval_scope: ApprovalScope | str,
    ) -> None:
        scope = ApprovalScope(approval_scope)
        if scope not in _PRODUCTION_SCOPES:
            raise ValueError(
                "production signal query requires a shadow, paper, or limited_live scope"
            )
        self._repository = repository
        self._scope = scope

    @property
    def approval_scope(self) -> ApprovalScope:
        return self._scope

    def get_snapshot(self, snapshot_id: str) -> SignalSnapshot | None:
        value = self._repository.get_snapshot(_identifier(snapshot_id, "snapshot_id"))
        if value is not None and value.approval_scope is not self._scope:
            raise SignalSnapshotQuerySurfaceDenied(
                "production signal query cannot cross its exact approval scope"
            )
        return value

    def list_snapshots(self) -> tuple[SignalSnapshot, ...]:
        return tuple(
            value
            for value in self._repository.list_snapshots()
            if value.approval_scope is self._scope
        )


__all__ = [
    "ProductionSignalSnapshotQueryService",
    "ResearchSignalSnapshotQueryService",
    "SignalSnapshotLedgerService",
    "SignalSnapshotQuerySurfaceDenied",
]
