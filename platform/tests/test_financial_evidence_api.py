import unittest
from datetime import UTC, date, datetime

from fastapi.testclient import TestClient

from a_share_platform.adapters.memory.financial_evidence import StaticFinancialEvidenceReader
from a_share_platform.api.app import create_app
from a_share_platform.application.financial_evidence import (
    DisclosureTimelineEntry,
    FactComparisonEntry,
    FactRevisionEntry,
    FactSelectionEntry,
    FinancialMismatchEntry,
    RawEvidenceEntry,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)
RAW_HASH = "sha256:" + "a" * 64


def evidence() -> RawEvidenceEntry:
    return RawEvidenceEntry(
        raw_object_id="raw:cninfo:1",
        object_kind="file",
        content_hash=RAW_HASH,
        source_url="https://www.cninfo.com.cn/disclosure/1.pdf",
        provider_id="cninfo",
        retrieved_at=NOW,
        media_type="application/pdf",
        license_id="cninfo-public-disclosure",
        retention_policy="metadata_only",
        retention_until=None,
        redistribution_allowed=False,
    )


def revision() -> FactRevisionEntry:
    return FactRevisionEntry(
        fact_id="fact:revenue:2024:v1",
        company_id="company:600519",
        security_id="security:600519",
        metric_code="income.revenue",
        value="174144000000",
        unit="currency",
        currency="CNY",
        report_period_end=date(2024, 12, 31),
        period_type="annual",
        statement_type="income_statement",
        announced_at=NOW,
        available_at=NOW,
        known_from=NOW,
        known_to=None,
        revision_sequence=1,
        provider_id="cninfo",
        source_field="营业收入",
        trust_state="normalized_current",
        quality_state="warning",
        mapping_version_id="mapping:cninfo:v1",
        source_object_id="raw:cninfo:1",
        dataset_version_id="dataset:financial:v1",
        quality_issue_ids=("issue:not-pit-verified",),
    )


class FinancialEvidenceApiTest(unittest.TestCase):
    def setUp(self) -> None:
        row = revision()
        reader = StaticFinancialEvidenceReader(
            disclosures=(
                DisclosureTimelineEntry(
                    disclosure_id="disclosure:1:v1",
                    document_key="cninfo:annual:600519:2024",
                    external_document_id="1",
                    company_id=row.company_id,
                    security_id=row.security_id,
                    source_system="cninfo",
                    title="2024 年年度报告（更正后）",
                    document_type="annual_report",
                    report_period_end=row.report_period_end,
                    published_at=NOW,
                    available_at=NOW,
                    first_tradable_at=NOW,
                    version_sequence=1,
                    status="corrected",
                    raw_object_id="raw:cninfo:1",
                    supersedes_disclosure_id="disclosure:1:v0",
                    status_reason="官方更正",
                ),
            ),
            fact_revisions=(row,),
            comparisons=(
                FactComparisonEntry(
                    company_id=row.company_id,
                    security_id=row.security_id,
                    metric_code=row.metric_code,
                    report_period_end=row.report_period_end,
                    period_type=row.period_type,
                    statement_type=row.statement_type,
                    decision_time=NOW,
                    system_time=NOW,
                    authority_rule_version="authority:official:v1",
                    current=FactSelectionEntry(
                        status="selected",
                        selected=row,
                        conflicting_fact_ids=(),
                        quality_issue_ids=row.quality_issue_ids,
                        blocks_downstream=False,
                        reason=None,
                    ),
                    strict=FactSelectionEntry(
                        status="unavailable",
                        selected=None,
                        conflicting_fact_ids=(),
                        quality_issue_ids=("issue:no-pit-verified-observation",),
                        blocks_downstream=True,
                        reason="no pit_verified observation is eligible",
                    ),
                ),
            ),
            mismatches=(
                FinancialMismatchEntry(
                    mismatch_id="mismatch:provider-value:1",
                    mismatch_type="provider_value_conflict",
                    status="blocking",
                    company_id=row.company_id,
                    security_id=row.security_id,
                    metric_code=row.metric_code,
                    report_period_end=row.report_period_end,
                    provider_ids=("cninfo", "factor_service"),
                    related_ids=(row.fact_id, "fact:factor-service:1"),
                    reason="provider values disagree",
                ),
            ),
            evidence=(evidence(),),
        )
        self.client = TestClient(create_app(financial_evidence=reader))

    def test_disclosure_fact_mismatch_and_evidence_endpoints_are_read_only(self) -> None:
        cases = {
            "/api/system/disclosures?company_id=company%3A600519": "官方更正",
            "/api/system/facts/revisions?company_id=company%3A600519": "fact:revenue:2024:v1",
            "/api/system/mismatches": "provider values disagree",
            "/api/system/evidence/raw%3Acninfo%3A1": "metadata_only",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(expected, str(response.json()["data"]))

        paths = self.client.get("/openapi.json").json()["paths"]
        for path, operations in paths.items():
            if path.startswith("/api/system/"):
                self.assertEqual(set(operations), {"get"})

    def test_current_strict_comparison_keeps_unverified_data_out_of_strict(self) -> None:
        response = self.client.get(
            "/api/system/facts/compare",
            params={
                "company_id": "company:600519",
                "security_id": "security:600519",
                "metric_code": "income.revenue",
                "report_period_end": "2024-12-31",
                "period_type": "annual",
                "statement_type": "income_statement",
                "decision_time": NOW.isoformat(),
                "system_time": NOW.isoformat(),
                "authority_rule_version": "authority:official:v1",
            },
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["current"]["status"], "selected")
        self.assertEqual(data["current"]["selected"]["trust_state"], "normalized_current")
        self.assertEqual(data["strict"]["status"], "unavailable")
        self.assertTrue(data["strict"]["blocks_downstream"])

    def test_default_runtime_has_no_financial_evidence_fixture(self) -> None:
        client = TestClient(create_app())
        self.assertEqual(client.get("/api/system/disclosures").json()["data"], [])
        self.assertEqual(client.get("/api/system/facts/revisions").json()["data"], [])
        self.assertEqual(client.get("/api/system/mismatches").json()["data"], [])


if __name__ == "__main__":
    unittest.main()
