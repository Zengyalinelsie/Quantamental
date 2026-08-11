"""Private-local content-addressed evidence for decoded provider responses.

This adapter deliberately records decoded provider values, not byte-exact HTTP
response bodies.  The distinction is embedded in the stored payload so this
evidence cannot later be mistaken for an official filing or promoted to PIT.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal

from a_share_platform.domain.disclosure import (
    RawObject,
    RawObjectKind,
    RetentionPolicy,
)
from a_share_platform.domain.financial_backfill import FinancialBackfillWorkUnit
from a_share_platform.ports.disclosure import RawObjectStore

_SCHEMA = "decoded-financial-provider-response:v1"


def _text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be empty")
    return value


def _aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _encoded_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("provider Decimal value must be finite")
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("provider float value must be finite")
        return {"type": "float", "value": repr(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": _aware(value, "provider datetime").isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    raise TypeError("provider response values must be immutable JSON-compatible scalars")


class LocalFinancialEvidenceCapture:
    """Create retained, non-redistributable evidence from decoded provider rows."""

    def __init__(
        self,
        *,
        object_store: RawObjectStore,
        license_id: str,
        retention_policy: RetentionPolicy,
        redistribution_allowed: bool,
        retention_until: date | None = None,
    ) -> None:
        if not hasattr(object_store, "put"):
            raise TypeError("object_store must implement put(payload)")
        policy = RetentionPolicy(retention_policy)
        if policy is RetentionPolicy.METADATA_ONLY:
            raise PermissionError("metadata_only policy forbids decoded response persistence")
        if type(redistribution_allowed) is not bool:
            raise TypeError("redistribution_allowed must be a boolean")
        if redistribution_allowed:
            raise PermissionError("private-local financial evidence cannot be redistributed")
        if policy is RetentionPolicy.UNTIL_DATE and not isinstance(retention_until, date):
            raise ValueError("until_date retention requires retention_until")
        if policy is not RetentionPolicy.UNTIL_DATE and retention_until is not None:
            raise ValueError("retention_until is only valid for until_date retention")
        self._object_store = object_store
        self._license_id = _text(license_id, "license_id")
        self._retention_policy = policy
        self._retention_until = retention_until
        self._redistribution_allowed = redistribution_allowed

    def capture_provider_response(
        self,
        *,
        work_unit: FinancialBackfillWorkUnit,
        provider_id: str,
        source_url: str,
        provider_records: tuple[Mapping[str, object], ...],
        retrieved_at: datetime,
    ) -> RawObject:
        if not isinstance(work_unit, FinancialBackfillWorkUnit):
            raise TypeError("work_unit must be a FinancialBackfillWorkUnit")
        provider = _text(provider_id, "provider_id")
        if provider != work_unit.provider_id:
            raise ValueError("provider does not match financial work unit")
        _text(source_url, "source_url")
        retrieved = _aware(retrieved_at, "retrieved_at")
        if not isinstance(provider_records, tuple):
            raise TypeError("provider_records must be a tuple")

        encoded_records: list[dict[str, object]] = []
        for record in provider_records:
            if not isinstance(record, Mapping):
                raise TypeError("provider_records must contain mappings")
            encoded_record: dict[str, object] = {}
            for field, value in record.items():
                name = _text(field, "provider field")
                if name in encoded_record:
                    raise ValueError("provider record fields must be unique")
                encoded_record[name] = _encoded_scalar(value)
            encoded_records.append(encoded_record)

        payload_value = {
            "byte_exact_http": False,
            "checkpoint_key": work_unit.checkpoint_key,
            "evidence_kind": "decoded_provider_extraction",
            "plan_id": work_unit.plan_id,
            "provider_id": provider,
            "provider_records": encoded_records,
            "provider_table": work_unit.provider_table,
            "report_period_end": work_unit.report_period_end.isoformat(),
            "retrieved_at": retrieved.isoformat(),
            "schema": _SCHEMA,
            "statement_type": work_unit.statement_type.value,
            "symbols": list(work_unit.symbols),
        }
        payload = json.dumps(
            payload_value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        storage_uri = self._object_store.put(payload)
        return RawObject(
            raw_object_id=f"raw:decoded-financial-response:{digest[:32]}",
            object_kind=RawObjectKind.RESPONSE,
            content_hash=f"sha256:{digest}",
            source_url=source_url,
            provider_id=provider,
            retrieved_at=retrieved,
            media_type="application/json",
            storage_uri=storage_uri,
            license_id=self._license_id,
            retention_policy=self._retention_policy,
            retention_until=self._retention_until,
            redistribution_allowed=self._redistribution_allowed,
        )


__all__ = ["LocalFinancialEvidenceCapture"]
