"""Separated repository ports for production features and research-only labels."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.features import FeatureSnapshot, LabelValue


class FeatureSnapshotReader(Protocol):
    """Production-safe reader; research labels are deliberately absent."""

    def get_snapshot(self, snapshot_id: str) -> FeatureSnapshot | None: ...


class FeatureSnapshotRepository(FeatureSnapshotReader, Protocol):
    def save_snapshot(self, value: FeatureSnapshot) -> FeatureSnapshot: ...


class ResearchLabelRepository(Protocol):
    """Research-only label storage, physically separate from feature reads."""

    def save_label(self, value: LabelValue) -> LabelValue: ...

    def get_label(self, content_hash: str) -> LabelValue | None: ...


__all__ = [
    "FeatureSnapshotReader",
    "FeatureSnapshotRepository",
    "ResearchLabelRepository",
]
