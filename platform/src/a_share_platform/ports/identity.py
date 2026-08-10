"""Trusted identity-provider port; request headers are not an implementation."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.application.permissions import Principal


class IdentityProvider(Protocol):
    def resolve_principal(self) -> Principal: ...
