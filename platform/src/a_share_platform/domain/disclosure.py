"""Immutable raw evidence and official-disclosure contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from urllib.parse import urlparse

from .governance import VersionConflictError

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class RawObjectKind(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    FILE = "file"


class RetentionPolicy(str, Enum):
    INDEFINITE = "indefinite"
    UNTIL_DATE = "until_date"
    METADATA_ONLY = "metadata_only"


class DisclosureStatus(str, Enum):
    PUBLISHED = "published"
    CORRECTED = "corrected"
    WITHDRAWN = "withdrawn"


class DisclosureSource(str, Enum):
    CNINFO = "cninfo"
    SSE = "sse"
    SZSE = "szse"
    BSE = "bse"
    COMPANY = "company"


class PublicationTimePrecision(str, Enum):
    """Precision supplied by the official index, never inferred from a clock value."""

    EXACT = "exact"
    DATE_ONLY = "date_only"


@dataclass(frozen=True)
class RawObject:
    """One immutable request, response, or document body plus its usage policy."""

    raw_object_id: str
    object_kind: RawObjectKind
    content_hash: str
    source_url: str
    provider_id: str
    retrieved_at: datetime
    media_type: str
    storage_uri: str
    license_id: str
    retention_policy: RetentionPolicy
    retention_until: date | None
    redistribution_allowed: bool
    parent_raw_object_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.raw_object_id, "raw_object_id")
        object.__setattr__(self, "object_kind", RawObjectKind(self.object_kind))
        if not isinstance(self.content_hash, str) or _SHA256.fullmatch(self.content_hash) is None:
            raise ValueError("content_hash must use sha256:<64 lowercase hex chars>")
        source_url = _text(self.source_url, "source_url")
        if urlparse(source_url).scheme not in {"http", "https"}:
            raise ValueError("source_url must be an http(s) URL")
        _text(self.provider_id, "provider_id")
        _aware(self.retrieved_at, "retrieved_at")
        _text(self.media_type, "media_type")
        _text(self.storage_uri, "storage_uri")
        _text(self.license_id, "license_id")
        policy = RetentionPolicy(self.retention_policy)
        object.__setattr__(self, "retention_policy", policy)
        if policy is RetentionPolicy.UNTIL_DATE and not isinstance(self.retention_until, date):
            raise ValueError("until_date retention requires retention_until")
        if policy is not RetentionPolicy.UNTIL_DATE and self.retention_until is not None:
            raise ValueError("retention_until is only valid for until_date retention")
        if type(self.redistribution_allowed) is not bool:
            raise TypeError("redistribution_allowed must be a boolean")
        if self.parent_raw_object_id is not None:
            _text(self.parent_raw_object_id, "parent_raw_object_id")
            if self.parent_raw_object_id == self.raw_object_id:
                raise ValueError("raw object cannot be its own parent")


@dataclass(frozen=True)
class OfficialDisclosure:
    """One public version in an official disclosure document chain."""

    disclosure_id: str
    document_key: str
    external_document_id: str
    company_id: str
    security_id: str | None
    source_system: DisclosureSource
    title: str
    document_type: str
    report_period_end: date | None
    published_at: datetime
    available_at: datetime
    first_tradable_at: datetime
    version_sequence: int
    status: DisclosureStatus
    raw_object_id: str
    supersedes_disclosure_id: str | None
    status_reason: str | None
    publication_time_precision: PublicationTimePrecision = PublicationTimePrecision.EXACT

    def __post_init__(self) -> None:
        for name in (
            "disclosure_id",
            "document_key",
            "external_document_id",
            "company_id",
            "title",
            "document_type",
            "raw_object_id",
        ):
            _text(str(getattr(self, name) or ""), name)
        if self.security_id is not None:
            _text(self.security_id, "security_id")
        object.__setattr__(self, "source_system", DisclosureSource(self.source_system))
        if self.report_period_end is not None and not isinstance(self.report_period_end, date):
            raise TypeError("report_period_end must be a date or None")
        published_at = _aware(self.published_at, "published_at")
        available_at = _aware(self.available_at, "available_at")
        first_tradable_at = _aware(self.first_tradable_at, "first_tradable_at")
        precision = PublicationTimePrecision(self.publication_time_precision)
        object.__setattr__(self, "publication_time_precision", precision)
        if precision is PublicationTimePrecision.DATE_ONLY and (
            published_at.hour,
            published_at.minute,
            published_at.second,
            published_at.microsecond,
        ) != (0, 0, 0, 0):
            raise ValueError("date_only publication metadata must use local midnight")
        if available_at < published_at:
            raise ValueError("available_at cannot precede published_at")
        if first_tradable_at < available_at:
            raise ValueError("first_tradable_at cannot precede available_at")
        if type(self.version_sequence) is not int or self.version_sequence < 0:
            raise ValueError("version_sequence must be a non-negative integer")
        status = DisclosureStatus(self.status)
        object.__setattr__(self, "status", status)
        if self.version_sequence == 0:
            if status is not DisclosureStatus.PUBLISHED:
                raise ValueError("version zero must be published")
            if self.supersedes_disclosure_id is not None:
                raise ValueError("version zero cannot supersede another disclosure")
            if self.status_reason is not None:
                raise ValueError("published version zero cannot have status_reason")
        else:
            _text(self.supersedes_disclosure_id or "", "supersedes_disclosure_id")
            if status is DisclosureStatus.PUBLISHED:
                raise ValueError("later versions must be corrected or withdrawn")
            _text(self.status_reason or "", "status_reason")


__all__ = [
    "DisclosureSource",
    "DisclosureStatus",
    "OfficialDisclosure",
    "PublicationTimePrecision",
    "RawObject",
    "RawObjectKind",
    "RetentionPolicy",
    "VersionConflictError",
]
