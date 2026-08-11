"""In-memory and explicitly unavailable valuation/improvement input sources."""

from __future__ import annotations

from a_share_platform.ports.valuation_inputs import (
    ValuationImprovementInputBundle,
    ValuationImprovementInputRequest,
)


class MemoryValuationImprovementInputSource:
    """Exact-key lookup over caller-supplied frozen bundles; no fixture fallback."""

    def __init__(self, values: tuple[ValuationImprovementInputBundle, ...] = ()) -> None:
        self._values: dict[
            tuple[object, ...],
            ValuationImprovementInputBundle,
        ] = {}
        for value in values:
            if not isinstance(value, ValuationImprovementInputBundle):
                raise TypeError("values must contain ValuationImprovementInputBundle")
            if value.frozen_key in self._values:
                raise ValueError("duplicate frozen valuation/improvement bundle")
            self._values[value.frozen_key] = value

    def load(
        self,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        if not isinstance(query, ValuationImprovementInputRequest):
            raise TypeError("query must be ValuationImprovementInputRequest")
        return self._values.get(query.frozen_key)


class UnavailableValuationImprovementInputSource:
    """Source used when no qualified provider adapter is configured."""

    def __init__(self) -> None:
        self.load_count = 0

    def load(
        self,
        query: ValuationImprovementInputRequest,
    ) -> ValuationImprovementInputBundle | None:
        if not isinstance(query, ValuationImprovementInputRequest):
            raise TypeError("query must be ValuationImprovementInputRequest")
        self.load_count += 1
        return None


__all__ = [
    "MemoryValuationImprovementInputSource",
    "UnavailableValuationImprovementInputSource",
]
