"""Use cases for immutable raw evidence and official disclosure versions."""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from a_share_platform.domain.disclosure import (
    OfficialDisclosure,
    RawObject,
    RawObjectKind,
    RetentionPolicy,
)
from a_share_platform.ports.disclosure import DisclosureRepository, RawObjectStore


class DisclosureLedger:
    def __init__(self, repository: DisclosureRepository, object_store: RawObjectStore) -> None:
        self._repository = repository
        self._object_store = object_store

    def capture_raw_object(
        self,
        *,
        raw_object_id: str,
        object_kind: RawObjectKind,
        payload: bytes,
        source_url: str,
        provider_id: str,
        retrieved_at: datetime,
        media_type: str,
        license_id: str,
        retention_policy: RetentionPolicy,
        redistribution_allowed: bool,
        retention_until: date | None = None,
        parent_raw_object_id: str | None = None,
    ) -> RawObject:
        retention_policy = RetentionPolicy(retention_policy)
        if retention_policy is RetentionPolicy.METADATA_ONLY:
            raise PermissionError("metadata_only policy forbids payload persistence")
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        digest = hashlib.sha256(payload).hexdigest()
        storage_uri = self._object_store.put(payload)
        value = RawObject(
            raw_object_id=raw_object_id,
            object_kind=object_kind,
            content_hash=f"sha256:{digest}",
            source_url=source_url,
            provider_id=provider_id,
            retrieved_at=retrieved_at,
            media_type=media_type,
            storage_uri=storage_uri,
            license_id=license_id,
            retention_policy=retention_policy,
            retention_until=retention_until,
            redistribution_allowed=redistribution_allowed,
            parent_raw_object_id=parent_raw_object_id,
        )
        return self._repository.register_raw_object(value)

    def register_disclosure(self, value: OfficialDisclosure) -> OfficialDisclosure:
        return self._repository.register_disclosure(value)
