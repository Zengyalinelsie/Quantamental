"""Explicit test and unavailable-runtime adapters for factor reviews."""

from __future__ import annotations

from typing import Never

from a_share_platform.domain.factor_reviews import (
    FactorPromotionReview,
    FactorReviewConflict,
)
from a_share_platform.ports.factor_reviews import FactorReviewStoreUnavailable


class InMemoryFactorReviewRepository:
    def __init__(self) -> None:
        self._reviews: dict[str, FactorPromotionReview] = {}

    def save_review(self, value: FactorPromotionReview) -> FactorPromotionReview:
        if not isinstance(value, FactorPromotionReview):
            raise TypeError("value must be a FactorPromotionReview")
        existing = self._reviews.get(value.review_id)
        if existing is not None:
            if existing != value:
                raise FactorReviewConflict(
                    f"immutable factor review conflict: {value.review_id}"
                )
            return existing
        self._reviews[value.review_id] = value
        return value

    def get_review(self, review_id: str) -> FactorPromotionReview | None:
        return self._reviews.get(review_id)

    def list_reviews(self) -> tuple[FactorPromotionReview, ...]:
        return tuple(self._reviews[key] for key in sorted(self._reviews))


class UnavailableFactorReviewRepository:
    def __init__(self, reason: str) -> None:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("unavailable factor review store reason must not be empty")
        self._reason = reason

    def _raise(self) -> Never:
        raise FactorReviewStoreUnavailable(self._reason)

    def save_review(self, value: FactorPromotionReview) -> FactorPromotionReview:
        del value
        self._raise()

    def get_review(self, review_id: str) -> FactorPromotionReview | None:
        del review_id
        self._raise()

    def list_reviews(self) -> tuple[FactorPromotionReview, ...]:
        self._raise()


__all__ = [
    "InMemoryFactorReviewRepository",
    "UnavailableFactorReviewRepository",
]
