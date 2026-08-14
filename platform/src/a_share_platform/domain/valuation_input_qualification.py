"""Qualification evidence for financial, price, and comparable valuation inputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .pit import DataTrustState
from .run_context import DataMode


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _texts(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    normalized = tuple(values)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{field_name} must be unique")
    for value in normalized:
        _text(value, field_name)
    return tuple(sorted(normalized))


class ValuationInputDomain(str, Enum):
    FINANCIAL = "financial"
    PRICE = "price"
    COMPARABLE = "comparable"


@dataclass(frozen=True)
class ValuationInputQualificationRequest:
    security_id: str
    decision_time: datetime
    data_mode: DataMode
    requested_trust_state: DataTrustState
    max_price_age_days: int

    def __post_init__(self) -> None:
        _text(self.security_id, "security_id")
        _aware(self.decision_time, "decision_time")
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.requested_trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("valuation input qualification cannot request raw trust")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical qualification requires pit_verified trust")
        if type(self.max_price_age_days) is not int or not 0 <= self.max_price_age_days <= 31:
            raise ValueError("max_price_age_days must be an integer between 0 and 31")
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "requested_trust_state", trust)


@dataclass(frozen=True)
class ValuationInputDomainEvidence:
    domain: ValuationInputDomain
    trust_state: DataTrustState | None
    dataset_version_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    content_hashes: tuple[str, ...]
    observation_count: int
    latest_source_available_at: datetime | None
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "domain", ValuationInputDomain(self.domain))
        if self.trust_state is not None:
            object.__setattr__(self, "trust_state", DataTrustState(self.trust_state))
        for field_name in (
            "dataset_version_ids",
            "source_ids",
            "observation_ids",
            "content_hashes",
        ):
            object.__setattr__(self, field_name, _texts(getattr(self, field_name), field_name))
        if type(self.observation_count) is not int or self.observation_count < 0:
            raise ValueError("observation_count must be a non-negative integer")
        if self.latest_source_available_at is not None:
            _aware(self.latest_source_available_at, "latest_source_available_at")
        blockers = _texts(self.blockers, "blockers")
        object.__setattr__(self, "blockers", blockers)
        if self.observation_count > 0 and not blockers:
            if (
                not self.dataset_version_ids
                or not self.source_ids
                or not self.observation_ids
                or not self.content_hashes
                or self.trust_state is None
                or self.latest_source_available_at is None
            ):
                raise ValueError("qualified domain evidence requires complete lineage")
            if self.trust_state is DataTrustState.RAW:
                raise ValueError("qualified domain evidence cannot use raw trust")

    @property
    def is_qualified(self) -> bool:
        return bool(
            self.observation_count > 0
            and not self.blockers
            and self.dataset_version_ids
            and self.source_ids
            and self.observation_ids
            and self.content_hashes
            and self.trust_state is not None
            and self.trust_state is not DataTrustState.RAW
            and self.latest_source_available_at is not None
        )


@dataclass(frozen=True)
class ValuationInputQualification:
    security_id: str
    decision_time: datetime
    data_mode: DataMode
    requested_trust_state: DataTrustState
    domain_evidence: tuple[ValuationInputDomainEvidence, ...]

    def __post_init__(self) -> None:
        _text(self.security_id, "security_id")
        decision_time = _aware(self.decision_time, "decision_time")
        mode = DataMode(self.data_mode)
        trust = DataTrustState(self.requested_trust_state)
        if trust is DataTrustState.RAW:
            raise ValueError("valuation input qualification cannot request raw trust")
        if mode is DataMode.STRICT_HISTORICAL and trust is not DataTrustState.PIT_VERIFIED:
            raise PermissionError("strict_historical qualification requires pit_verified trust")
        values = tuple(self.domain_evidence)
        if any(not isinstance(value, ValuationInputDomainEvidence) for value in values):
            raise TypeError("domain_evidence must contain ValuationInputDomainEvidence")
        domains = tuple(value.domain for value in values)
        if len(domains) != len(set(domains)) or set(domains) != set(ValuationInputDomain):
            raise ValueError("qualification requires financial, price, and comparable evidence")
        for value in values:
            if (
                value.latest_source_available_at is not None
                and value.latest_source_available_at > decision_time
            ):
                raise ValueError(
                    f"{value.domain.value} latest availability exceeds decision_time"
                )
        object.__setattr__(self, "data_mode", mode)
        object.__setattr__(self, "requested_trust_state", trust)
        object.__setattr__(
            self,
            "domain_evidence",
            tuple(sorted(values, key=lambda value: value.domain.value)),
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        values: list[str] = []
        for evidence in self.domain_evidence:
            values.extend(
                f"{evidence.domain.value}: {blocker}" for blocker in evidence.blockers
            )
            if not evidence.is_qualified and not evidence.blockers:
                values.append(f"{evidence.domain.value}: qualified evidence is unavailable")
            if evidence.trust_state is not self.requested_trust_state:
                actual = "unavailable" if evidence.trust_state is None else evidence.trust_state.value
                values.append(
                    f"{evidence.domain.value}: requested {self.requested_trust_state.value} "
                    f"but observed {actual}"
                )
        return tuple(dict.fromkeys(values))

    @property
    def is_qualified(self) -> bool:
        return not self.blockers and all(value.is_qualified for value in self.domain_evidence)

    @property
    def dataset_version_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    dataset_id
                    for evidence in self.domain_evidence
                    for dataset_id in evidence.dataset_version_ids
                }
            )
        )


__all__ = [
    "ValuationInputDomain",
    "ValuationInputDomainEvidence",
    "ValuationInputQualification",
    "ValuationInputQualificationRequest",
]
