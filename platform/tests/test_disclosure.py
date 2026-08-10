import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from a_share_platform.adapters.memory.disclosure import InMemoryDisclosureRepository
from a_share_platform.adapters.object_store.local import LocalRawObjectStore
from a_share_platform.application.disclosure_ledger import DisclosureLedger
from a_share_platform.domain.disclosure import (
    DisclosureStatus,
    OfficialDisclosure,
    PublicationTimePrecision,
    RawObject,
    RawObjectKind,
    RetentionPolicy,
    VersionConflictError,
)

PUBLISHED_AT = datetime(2024, 3, 28, 10, tzinfo=UTC)
AVAILABLE_AT = datetime(2024, 3, 28, 10, 1, tzinfo=UTC)
FIRST_TRADABLE_AT = datetime(2024, 3, 28, 10, 2, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def raw_object(*, raw_object_id: str = "raw:annual-report:v1", content_hash: str = HASH_A) -> RawObject:
    return RawObject(
        raw_object_id=raw_object_id,
        object_kind=RawObjectKind.FILE,
        content_hash=content_hash,
        source_url="https://www.cninfo.com.cn/disclosure/annual-report.pdf",
        provider_id="provider:cninfo",
        retrieved_at=AVAILABLE_AT,
        media_type="application/pdf",
        storage_uri=f"file:///objects/{content_hash.removeprefix('sha256:')}",
        license_id="license:cninfo-public-disclosure:v1",
        retention_policy=RetentionPolicy.INDEFINITE,
        retention_until=None,
        redistribution_allowed=False,
    )


def disclosure(
    *,
    disclosure_id: str = "disclosure:000001:2023-annual:v1",
    raw_object_id: str = "raw:annual-report:v1",
    version_sequence: int = 0,
    status: DisclosureStatus = DisclosureStatus.PUBLISHED,
    supersedes_disclosure_id: str | None = None,
    status_reason: str | None = None,
) -> OfficialDisclosure:
    return OfficialDisclosure(
        disclosure_id=disclosure_id,
        document_key="cninfo:000001:2023-annual",
        external_document_id="1219500000",
        company_id="company:ping-an-bank",
        security_id="security:000001-szse",
        source_system="cninfo",
        title="平安银行股份有限公司2023年年度报告",
        document_type="annual_report",
        report_period_end=date(2023, 12, 31),
        published_at=PUBLISHED_AT,
        available_at=AVAILABLE_AT,
        first_tradable_at=FIRST_TRADABLE_AT,
        version_sequence=version_sequence,
        status=status,
        raw_object_id=raw_object_id,
        supersedes_disclosure_id=supersedes_disclosure_id,
        status_reason=status_reason,
    )


class RawObjectTest(unittest.TestCase):
    def test_raw_object_requires_auditable_source_hash_license_and_retention(self) -> None:
        value = raw_object()
        self.assertEqual(value.object_kind, RawObjectKind.FILE)
        self.assertEqual(value.retention_policy, RetentionPolicy.INDEFINITE)
        with self.assertRaisesRegex(ValueError, "sha256"):
            replace(value, content_hash="not-a-hash")
        with self.assertRaisesRegex(ValueError, "source_url"):
            replace(value, source_url="")
        with self.assertRaisesRegex(ValueError, "license_id"):
            replace(value, license_id="")

    def test_until_date_retention_requires_a_future_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "retention_until"):
            replace(
                raw_object(),
                retention_policy=RetentionPolicy.UNTIL_DATE,
                retention_until=None,
            )
        value = replace(
            raw_object(),
            retention_policy=RetentionPolicy.UNTIL_DATE,
            retention_until=date(2030, 12, 31),
        )
        self.assertEqual(value.retention_until, date(2030, 12, 31))

    def test_raw_object_metadata_is_immutable(self) -> None:
        value = raw_object()
        with self.assertRaises(FrozenInstanceError):
            value.provider_id = "provider:other"  # type: ignore[misc]


class OfficialDisclosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryDisclosureRepository()
        self.repository.register_raw_object(raw_object())

    def test_publication_availability_and_first_trade_are_ordered(self) -> None:
        with self.assertRaisesRegex(ValueError, "available_at"):
            replace(disclosure(), available_at=PUBLISHED_AT.replace(hour=9))
        with self.assertRaisesRegex(ValueError, "first_tradable_at"):
            replace(disclosure(), first_tradable_at=PUBLISHED_AT)

    def test_date_only_publication_is_explicit_and_cannot_masquerade_as_exact(self) -> None:
        shanghai = ZoneInfo("Asia/Shanghai")
        value = replace(
            disclosure(),
            published_at=datetime(2025, 4, 26, 0, 0, tzinfo=shanghai),
            available_at=datetime(2025, 4, 28, 9, 15, tzinfo=shanghai),
            first_tradable_at=datetime(2025, 4, 28, 9, 30, tzinfo=shanghai),
            publication_time_precision=PublicationTimePrecision.DATE_ONLY,
        )
        self.assertEqual(value.publication_time_precision, PublicationTimePrecision.DATE_ONLY)
        with self.assertRaisesRegex(ValueError, "date_only"):
            replace(value, published_at=value.published_at.replace(hour=18))

    def test_original_correction_and_withdrawal_form_one_version_chain(self) -> None:
        original = self.repository.register_disclosure(disclosure())
        correction_raw = raw_object(
            raw_object_id="raw:annual-report:v2",
            content_hash=HASH_B,
        )
        self.repository.register_raw_object(correction_raw)
        correction = self.repository.register_disclosure(
            disclosure(
                disclosure_id="disclosure:000001:2023-annual:v2",
                raw_object_id=correction_raw.raw_object_id,
                version_sequence=1,
                status=DisclosureStatus.CORRECTED,
                supersedes_disclosure_id=original.disclosure_id,
                status_reason="会计差错更正",
            )
        )
        withdrawal_raw = raw_object(
            raw_object_id="raw:annual-report:withdrawal",
            content_hash="sha256:" + "c" * 64,
        )
        self.repository.register_raw_object(withdrawal_raw)
        withdrawal = self.repository.register_disclosure(
            disclosure(
                disclosure_id="disclosure:000001:2023-annual:v3",
                raw_object_id=withdrawal_raw.raw_object_id,
                version_sequence=2,
                status=DisclosureStatus.WITHDRAWN,
                supersedes_disclosure_id=correction.disclosure_id,
                status_reason="发行人撤回",
            )
        )
        self.assertEqual(
            self.repository.timeline(original.document_key),
            (original, correction, withdrawal),
        )

    def test_version_chain_rejects_gaps_cross_document_links_and_silent_corrections(self) -> None:
        original = self.repository.register_disclosure(disclosure())
        self.repository.register_raw_object(
            raw_object(raw_object_id="raw:annual-report:v2", content_hash=HASH_B)
        )
        with self.assertRaisesRegex(ValueError, "status_reason"):
            self.repository.register_disclosure(
                disclosure(
                    disclosure_id="disclosure:000001:2023-annual:v2",
                    raw_object_id="raw:annual-report:v2",
                    version_sequence=1,
                    status=DisclosureStatus.CORRECTED,
                    supersedes_disclosure_id=original.disclosure_id,
                )
            )
        with self.assertRaisesRegex(VersionConflictError, "next version"):
            self.repository.register_disclosure(
                disclosure(
                    disclosure_id="disclosure:000001:2023-annual:v3",
                    raw_object_id="raw:annual-report:v2",
                    version_sequence=2,
                    status=DisclosureStatus.CORRECTED,
                    supersedes_disclosure_id=original.disclosure_id,
                    status_reason="invalid gap",
                )
            )

    def test_later_version_cannot_be_published_before_the_version_it_replaces(self) -> None:
        original = self.repository.register_disclosure(disclosure())
        self.repository.register_raw_object(
            raw_object(raw_object_id="raw:annual-report:v2", content_hash=HASH_B)
        )
        with self.assertRaisesRegex(VersionConflictError, "publication time"):
            self.repository.register_disclosure(
                replace(
                    disclosure(
                        disclosure_id="disclosure:000001:2023-annual:v2",
                        raw_object_id="raw:annual-report:v2",
                        version_sequence=1,
                        status=DisclosureStatus.CORRECTED,
                        supersedes_disclosure_id=original.disclosure_id,
                        status_reason="invalid clock",
                    ),
                    published_at=datetime(2024, 3, 27, 10, tzinfo=UTC),
                    available_at=datetime(2024, 3, 27, 10, 1, tzinfo=UTC),
                    first_tradable_at=datetime(2024, 3, 27, 10, 2, tzinfo=UTC),
                )
            )

    def test_disclosure_cannot_reference_missing_raw_evidence(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw object does not exist"):
            self.repository.register_disclosure(
                disclosure(raw_object_id="raw:missing")
            )

    def test_immutable_identifiers_cannot_be_reused_with_new_content(self) -> None:
        first = self.repository.register_raw_object(raw_object())
        self.assertIs(self.repository.register_raw_object(first), first)
        with self.assertRaisesRegex(VersionConflictError, "raw:annual-report:v1"):
            self.repository.register_raw_object(replace(first, content_hash=HASH_B))


class DisclosureLedgerTest(unittest.TestCase):
    def test_request_response_and_file_payloads_are_captured_with_computed_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = InMemoryDisclosureRepository()
            ledger = DisclosureLedger(repository, LocalRawObjectStore(Path(directory)))
            captured = tuple(
                ledger.capture_raw_object(
                    raw_object_id=f"raw:capture:{kind.value}",
                    object_kind=kind,
                    payload=f"{kind.value} bytes".encode(),
                    source_url="https://www.cninfo.com.cn/api/disclosure",
                    provider_id="provider:cninfo",
                    retrieved_at=AVAILABLE_AT,
                    media_type="application/json" if kind is not RawObjectKind.FILE else "application/pdf",
                    license_id="license:cninfo-public-disclosure:v1",
                    retention_policy=RetentionPolicy.INDEFINITE,
                    redistribution_allowed=False,
                )
                for kind in RawObjectKind
            )
            self.assertEqual(
                tuple(item.object_kind for item in captured),
                tuple(RawObjectKind),
            )
            self.assertTrue(all(item.content_hash.startswith("sha256:") for item in captured))
            self.assertTrue(all(item.storage_uri.startswith("file://") for item in captured))

    def test_metadata_only_license_fails_closed_before_storing_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = InMemoryDisclosureRepository()
            ledger = DisclosureLedger(repository, LocalRawObjectStore(Path(directory)))
            with self.assertRaisesRegex(PermissionError, "metadata_only"):
                ledger.capture_raw_object(
                    raw_object_id="raw:forbidden",
                    object_kind=RawObjectKind.RESPONSE,
                    payload=b"must not be persisted",
                    source_url="https://provider.example/api",
                    provider_id="provider:restricted",
                    retrieved_at=AVAILABLE_AT,
                    media_type="application/json",
                    license_id="license:restricted:v1",
                    retention_policy=RetentionPolicy.METADATA_ONLY,
                    redistribution_allowed=False,
                )
            self.assertEqual(repository.list_raw_objects(), ())


if __name__ == "__main__":
    unittest.main()
