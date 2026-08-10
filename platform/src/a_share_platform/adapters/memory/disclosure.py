"""In-memory disclosure repository used by domain and API contract tests."""

from __future__ import annotations

from a_share_platform.domain.disclosure import OfficialDisclosure, RawObject
from a_share_platform.domain.governance import VersionConflictError


class InMemoryDisclosureRepository:
    def __init__(self) -> None:
        self._raw_objects: dict[str, RawObject] = {}
        self._disclosures: dict[str, OfficialDisclosure] = {}
        self._timelines: dict[str, list[OfficialDisclosure]] = {}

    def register_raw_object(self, value: RawObject) -> RawObject:
        if existing := self._raw_objects.get(value.raw_object_id):
            if existing != value:
                raise VersionConflictError(
                    f"immutable raw object identifier conflict: {value.raw_object_id}"
                )
            return existing
        if value.parent_raw_object_id is not None and value.parent_raw_object_id not in self._raw_objects:
            raise ValueError(f"parent raw object does not exist: {value.parent_raw_object_id}")
        self._raw_objects[value.raw_object_id] = value
        return value

    def get_raw_object(self, raw_object_id: str) -> RawObject | None:
        return self._raw_objects.get(raw_object_id)

    def list_raw_objects(self) -> tuple[RawObject, ...]:
        return tuple(self._raw_objects.values())

    def register_disclosure(self, value: OfficialDisclosure) -> OfficialDisclosure:
        if existing := self._disclosures.get(value.disclosure_id):
            if existing != value:
                raise VersionConflictError(
                    f"immutable disclosure identifier conflict: {value.disclosure_id}"
                )
            return existing
        if value.raw_object_id not in self._raw_objects:
            raise ValueError(f"raw object does not exist: {value.raw_object_id}")
        timeline = self._timelines.setdefault(value.document_key, [])
        if not timeline:
            if value.version_sequence != 0:
                raise VersionConflictError("first disclosure must be version zero")
        else:
            latest = timeline[-1]
            if value.version_sequence != latest.version_sequence + 1:
                raise VersionConflictError("disclosure must be the next version in the chain")
            if value.supersedes_disclosure_id != latest.disclosure_id:
                raise VersionConflictError("disclosure must supersede the latest version")
            if value.published_at < latest.published_at:
                raise VersionConflictError(
                    "disclosure publication time cannot precede the version it replaces"
                )
            if (value.company_id, value.security_id, value.source_system) != (
                latest.company_id,
                latest.security_id,
                latest.source_system,
            ):
                raise VersionConflictError("disclosure version identity cannot change")
        self._disclosures[value.disclosure_id] = value
        timeline.append(value)
        return value

    def timeline(self, document_key: str) -> tuple[OfficialDisclosure, ...]:
        return tuple(self._timelines.get(document_key, ()))
