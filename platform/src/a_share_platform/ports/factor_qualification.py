"""Ports for read-only factor qualification inspection and audit persistence."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.factor_qualification import (
    FactorQualificationAudit,
    FactorQualificationRequest,
    FactorQualificationSnapshot,
    FactorQualificationTarget,
)


class FactorQualificationSource(Protocol):
    def inspect(
        self,
        request: FactorQualificationRequest,
        targets: tuple[FactorQualificationTarget, ...],
    ) -> FactorQualificationSnapshot: ...


class FactorQualificationRepository(Protocol):
    def save(self, value: FactorQualificationAudit) -> bool: ...


__all__ = ["FactorQualificationRepository", "FactorQualificationSource"]
