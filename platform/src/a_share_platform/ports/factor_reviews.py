"""Repository port for immutable factor promotion review records."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.factor_reviews import FactorPromotionReview


class FactorReviewStoreUnavailable(RuntimeError):
    """The durable factor review ledger is not configured or reachable."""


class FactorReviewRepository(Protocol):
    def save_review(self, value: FactorPromotionReview) -> FactorPromotionReview: ...

    def get_review(self, review_id: str) -> FactorPromotionReview | None: ...

    def list_reviews(self) -> tuple[FactorPromotionReview, ...]: ...


__all__ = ["FactorReviewRepository", "FactorReviewStoreUnavailable"]
