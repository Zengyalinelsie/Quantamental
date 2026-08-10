import tempfile
import unittest
from pathlib import Path

from a_share_platform.domain.pit_fixtures import PITFixturePack

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MANIFEST = PLATFORM_ROOT / "fixtures" / "p3" / "pit_fixture_pack.v1.json"


class PITFixturePackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.pack = PITFixturePack.load(FIXTURE_MANIFEST)

    def test_real_pack_satisfies_every_w04_scenario_without_runtime_fake_data(self) -> None:
        self.pack.require_w04_capability_coverage()
        self.assertGreaterEqual(len(self.pack.company_codes), 3)
        self.assertLessEqual(len(self.pack.company_codes), 5)
        self.assertGreaterEqual(len(self.pack.revision_chains), 2)
        self.assertEqual(
            self.pack.required_scenarios,
            {
                "normal_after_hours_annual_report",
                "pre_market_availability",
                "weekend_disclosure",
                "financial_correction",
                "multiple_versions_same_period",
                "unit_or_currency_conflict",
                "missing_field",
                "one_off_item",
                "provider_official_mismatch",
            },
        )

    def test_revision_expectations_change_only_at_conservative_availability(self) -> None:
        for chain in self.pack.revision_chains:
            with self.subTest(chain=chain.chain_id):
                self.assertLess(chain.original.available_at, chain.corrected.available_at)
                self.assertNotEqual(chain.original.expected_facts, chain.corrected.expected_facts)
                self.assertTrue(chain.corrected.supersedes_external_document_id)

    def test_every_evidence_item_has_explicit_ingestion_and_version_metadata(self) -> None:
        for evidence in self.pack.evidence:
            with self.subTest(evidence=evidence.external_document_id):
                self.assertGreaterEqual(evidence.retrieved_at, evidence.official_reported_at)
                self.assertTrue(evidence.document_key)
                self.assertTrue(evidence.document_type)
                self.assertGreaterEqual(evidence.version_sequence, 0)
                if evidence.version_sequence == 0:
                    self.assertEqual(evidence.status, "published")
                    self.assertIsNone(evidence.supersedes_external_document_id)
                else:
                    self.assertEqual(evidence.status, "corrected")
                    self.assertTrue(evidence.supersedes_external_document_id)
                    self.assertTrue(evidence.status_reason)

    def test_raw_evidence_verifier_fails_closed_on_missing_or_wrong_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(FileNotFoundError, "raw evidence"):
                self.pack.verify_raw_evidence(root)
            first = self.pack.evidence[0]
            (root / first.local_filename).write_bytes(b"not the official PDF")
            with self.assertRaisesRegex((FileNotFoundError, ValueError), "raw evidence|hash"):
                self.pack.verify_raw_evidence(root)


if __name__ == "__main__":
    unittest.main()
