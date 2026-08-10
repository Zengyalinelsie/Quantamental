"""Ports for official disclosure metadata and immutable raw bytes."""

from __future__ import annotations

from typing import Protocol

from a_share_platform.domain.disclosure import OfficialDisclosure, RawObject


class DisclosureRepository(Protocol):
    def register_raw_object(self, value: RawObject) -> RawObject: ...

    def get_raw_object(self, raw_object_id: str) -> RawObject | None: ...

    def list_raw_objects(self) -> tuple[RawObject, ...]: ...

    def register_disclosure(self, value: OfficialDisclosure) -> OfficialDisclosure: ...

    def timeline(self, document_key: str) -> tuple[OfficialDisclosure, ...]: ...


class RawObjectStore(Protocol):
    def put(self, payload: bytes) -> str: ...
