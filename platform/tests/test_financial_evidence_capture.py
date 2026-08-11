import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from a_share_platform.adapters.object_store.financial_evidence import (
    LocalFinancialEvidenceCapture,
)
from a_share_platform.adapters.object_store.local import LocalRawObjectStore
from a_share_platform.domain.disclosure import RawObjectKind, RetentionPolicy
from a_share_platform.domain.financial_backfill import FinancialBackfillWorkUnit
from a_share_platform.domain.metrics import StatementType

NOW = datetime(2026, 8, 11, 4, tzinfo=UTC)


def work_unit(*, provider_id: str = "akshare") -> FinancialBackfillWorkUnit:
    return FinancialBackfillWorkUnit(
        plan_id="financial-backfill:csi300:akshare-pilot:v1",
        checkpoint_key=(
            "financial_statement:akshare:csi300:balance_sheet:2024-12-31:bucket-0001"
        ),
        provider_id=provider_id,
        provider_profile_version="financial-source:akshare:v1",
        benchmark_id="index:CSI:000300",
        universe_version_id="universe:index-000300:2026-08-10:v1",
        mapping_version_id="mapping:akshare-eastmoney:v1",
        statement_type=StatementType.BALANCE_SHEET,
        provider_table="balance_sheet",
        report_period_end=date(2024, 12, 31),
        symbol_bucket_id="bucket-0001",
        symbols=("SH.600000",),
    )


class LocalFinancialEvidenceCaptureTest(unittest.TestCase):
    def test_decoded_records_are_content_addressed_without_claiming_http_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = LocalFinancialEvidenceCapture(
                object_store=LocalRawObjectStore(root / "objects"),
                license_id="akshare-private-local-research:v1",
                retention_policy=RetentionPolicy.INDEFINITE,
                redistribution_allowed=False,
            )
            records = (
                {
                    "SECURITY_CODE": "600000",
                    "REPORT_DATE": "2024-12-31",
                    "TOTAL_ASSETS": Decimal("123.4500"),
                },
            )

            first = capture.capture_provider_response(
                work_unit=work_unit(),
                provider_id="akshare",
                source_url="https://akshare.akfamily.xyz/data/stock/stock.html",
                provider_records=records,
                retrieved_at=NOW,
            )
            repeated = capture.capture_provider_response(
                work_unit=work_unit(),
                provider_id="akshare",
                source_url="https://akshare.akfamily.xyz/data/stock/stock.html",
                provider_records=records,
                retrieved_at=NOW,
            )

            self.assertEqual(first, repeated)
            self.assertEqual(first.object_kind, RawObjectKind.RESPONSE)
            self.assertEqual(first.provider_id, "akshare")
            self.assertEqual(first.retention_policy, RetentionPolicy.INDEFINITE)
            self.assertFalse(first.redistribution_allowed)
            self.assertTrue(first.raw_object_id.startswith("raw:decoded-financial-response:"))
            self.assertTrue(first.content_hash.startswith("sha256:"))
            payload = json.loads(Path(first.storage_uri.removeprefix("file://")).read_bytes())
            self.assertEqual(payload["schema"], "decoded-financial-provider-response:v1")
            self.assertFalse(payload["byte_exact_http"])
            self.assertEqual(payload["evidence_kind"], "decoded_provider_extraction")
            self.assertEqual(payload["checkpoint_key"], work_unit().checkpoint_key)
            self.assertEqual(
                payload["provider_records"][0]["TOTAL_ASSETS"],
                {"type": "decimal", "value": "123.4500"},
            )

    def test_provider_mismatch_and_metadata_only_retention_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalRawObjectStore(Path(directory))
            with self.assertRaisesRegex(PermissionError, "metadata_only"):
                LocalFinancialEvidenceCapture(
                    object_store=store,
                    license_id="akshare-private-local-research:v1",
                    retention_policy=RetentionPolicy.METADATA_ONLY,
                    redistribution_allowed=False,
                )
            capture = LocalFinancialEvidenceCapture(
                object_store=store,
                license_id="akshare-private-local-research:v1",
                retention_policy=RetentionPolicy.INDEFINITE,
                redistribution_allowed=False,
            )
            with self.assertRaisesRegex(ValueError, "provider"):
                capture.capture_provider_response(
                    work_unit=work_unit(),
                    provider_id="another-provider",
                    source_url="https://example.test/provider",
                    provider_records=({"value": "1"},),
                    retrieved_at=NOW,
                )

    def test_non_finite_or_mutable_provider_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = LocalFinancialEvidenceCapture(
                object_store=LocalRawObjectStore(Path(directory)),
                license_id="akshare-private-local-research:v1",
                retention_policy=RetentionPolicy.INDEFINITE,
                redistribution_allowed=False,
            )
            for invalid in (float("nan"), ["mutable"]):
                with self.subTest(invalid=invalid), self.assertRaises((TypeError, ValueError)):
                    capture.capture_provider_response(
                        work_unit=work_unit(),
                        provider_id="akshare",
                        source_url="https://example.test/provider",
                        provider_records=({"value": invalid},),
                        retrieved_at=NOW,
                    )


if __name__ == "__main__":
    unittest.main()
