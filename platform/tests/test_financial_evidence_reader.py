import unittest
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Self

from a_share_platform.adapters.postgres.financial_evidence import (
    PostgresFinancialEvidenceReader,
)
from a_share_platform.application.financial_evidence import (
    FactComparisonQuery,
    FactIdentityQuery,
    compare_fact_modes,
)
from a_share_platform.domain.metrics import MetricUnit, StatementType
from a_share_platform.domain.pit import (
    AuthorityRule,
    DataQualityState,
    DataTrustState,
    FactObservation,
    FinancialPeriodType,
)

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)


def fact(*, fact_id: str = "fact:current", provider_id: str = "provider:official") -> FactObservation:
    return FactObservation(
        fact_id=fact_id,
        company_id="company:600519",
        security_id="security:600519",
        metric_code="income.revenue",
        value=174_144_000_000,
        unit=MetricUnit.CURRENCY,
        currency="CNY",
        report_period_end=date(2024, 12, 31),
        period_type=FinancialPeriodType.ANNUAL,
        statement_type=StatementType.INCOME_STATEMENT,
        announced_at=NOW,
        available_at=NOW,
        known_from=NOW,
        known_to=None,
        revision_sequence=0,
        provider_id=provider_id,
        source_field="营业收入",
        raw_object_hash="sha256:" + "a" * 64,
        trust_state=DataTrustState.NORMALIZED_CURRENT,
        quality_state=DataQualityState.PASSED,
        mapping_version_id="mapping:official:v1",
        source_object_id="raw:official:1",
        dataset_version_id="dataset:financial:v1",
        quality_issue_ids=(),
    )


def query() -> FactComparisonQuery:
    return FactComparisonQuery(
        company_id="company:600519",
        security_id="security:600519",
        metric_code="income.revenue",
        report_period_end=date(2024, 12, 31),
        period_type="annual",
        statement_type="income_statement",
        decision_time=NOW,
        system_time=NOW,
        authority_rule_version="authority:official:v1",
    )


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class FakeTransaction:
    def __init__(self, connection: "FakeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> Self:
        self.connection.transactions += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeConnection(AbstractContextManager["FakeConnection"]):
    def __init__(self, rows: dict[str, list[tuple[object, ...]]]) -> None:
        self.rows = rows
        self.calls: list[str] = []
        self.transactions = 0

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> FakeResult:
        self.calls.append(sql)
        if "FROM evidence.official_disclosures" in sql:
            return FakeResult(self.rows.get("disclosures", []))
        if "FROM governance.financial_authority_rules" in sql:
            return FakeResult(self.rows.get("authority", []))
        if "FROM canonical.financial_fact_observations" in sql:
            return FakeResult(self.rows.get("facts", []))
        if "FROM governance.unmapped_metric_fields" in sql:
            return FakeResult(self.rows.get("unmapped", []))
        if "FROM evidence.raw_objects" in sql:
            return FakeResult(self.rows.get("evidence", []))
        return FakeResult([])


class Factory:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __call__(self) -> AbstractContextManager[FakeConnection]:
        return self.connection


def fact_row(value: FactObservation) -> tuple[object, ...]:
    return (
        value.fact_id,
        value.company_id,
        value.security_id,
        value.metric_code,
        value.value,
        value.unit.value,
        value.currency,
        value.report_period_end,
        value.period_type.value,
        value.statement_type.value,
        value.announced_at,
        value.available_at,
        value.known_from,
        value.known_to,
        value.revision_sequence,
        value.provider_id,
        value.source_field,
        value.raw_object_hash,
        value.trust_state.value,
        value.quality_state.value,
        value.mapping_version_id,
        value.source_object_id,
        value.dataset_version_id,
        list(value.quality_issue_ids),
    )


class FinancialEvidenceSelectionTest(unittest.TestCase):
    def test_normalized_current_is_selected_only_on_current_side(self) -> None:
        result = compare_fact_modes(
            (fact(),),
            query(),
            AuthorityRule("authority:official:v1", ("provider:official",)),
        )

        self.assertEqual(result.current.status, "selected")
        self.assertEqual(result.current.selected.trust_state, "normalized_current")  # type: ignore[union-attr]
        self.assertEqual(result.strict.status, "unavailable")
        self.assertTrue(result.strict.blocks_downstream)

    def test_provider_disagreement_is_visible_and_blocks_downstream(self) -> None:
        other = replace(
            fact(fact_id="fact:vendor", provider_id="provider:vendor"),
            value=174_000_000_000,
            mapping_version_id="mapping:vendor:v1",
        )
        result = compare_fact_modes(
            (fact(), other),
            query(),
            AuthorityRule(
                "authority:official:v1",
                ("provider:official", "provider:vendor"),
            ),
        )

        self.assertEqual(result.current.status, "blocked")
        self.assertEqual(result.current.conflicting_fact_ids, ("fact:vendor",))


class PostgresFinancialEvidenceReaderTest(unittest.TestCase):
    def test_jsonb_numeric_text_is_not_reparsed_through_binary_float(self) -> None:
        exact = "17085765657.950001"
        row = fact_row(replace(fact(), value=exact))
        connection = FakeConnection({"facts": [row]})
        restored = PostgresFinancialEvidenceReader(Factory(connection)).list_fact_revisions(
            # A company filter is sufficient for this read-model round trip.
            FactIdentityQuery(company_id="company:600519")
        )
        self.assertEqual(restored[0].value, exact)
        self.assertIsInstance(restored[0].value, str)

    def test_disclosure_preserves_official_publication_time_precision(self) -> None:
        disclosure = (
            "disclosure:1",
            "document:1",
            "1",
            "company:600519",
            "security:600519",
            "cninfo",
            "年度报告",
            "annual_report",
            date(2024, 12, 31),
            NOW,
            NOW,
            NOW,
            "date_only",
            0,
            "published",
            "raw:1",
            None,
            None,
        )
        connection = FakeConnection({"disclosures": [disclosure]})
        rows = PostgresFinancialEvidenceReader(Factory(connection)).list_disclosures(
            "company:600519"
        )
        self.assertEqual(rows[0].publication_time_precision, "date_only")

    def test_comparison_reads_facts_and_versioned_authority_in_read_only_transactions(self) -> None:
        connection = FakeConnection(
            {
                "facts": [fact_row(fact())],
                "authority": [("authority:official:v1", ["provider:official"])],
            }
        )
        reader = PostgresFinancialEvidenceReader(Factory(connection))

        result = reader.compare_fact(query())

        self.assertIsNotNone(result)
        self.assertEqual(result.current.status, "selected")  # type: ignore[union-attr]
        self.assertEqual(result.strict.status, "unavailable")  # type: ignore[union-attr]
        self.assertEqual(connection.transactions, 2)
        self.assertEqual(
            sum(sql.strip() == "SET TRANSACTION READ ONLY" for sql in connection.calls),
            2,
        )

    def test_mismatch_queue_combines_unmapped_quality_and_provider_conflicts(self) -> None:
        blocked = replace(
            fact(fact_id="fact:blocked"),
            quality_state=DataQualityState.BLOCKED,
            quality_issue_ids=("issue:balance",),
        )
        other = replace(
            fact(fact_id="fact:vendor", provider_id="provider:vendor"),
            value=1,
            mapping_version_id="mapping:vendor:v1",
        )
        connection = FakeConnection(
            {
                "unmapped": [("unmapped:1", "provider:vendor", "UNKNOWN", "raw:vendor:1")],
                "facts": [fact_row(blocked), fact_row(other)],
            }
        )

        rows = PostgresFinancialEvidenceReader(Factory(connection)).list_mismatches()

        self.assertEqual(
            {row.mismatch_type for row in rows},
            {"unmapped_field", "quality_block", "provider_value_conflict"},
        )


if __name__ == "__main__":
    unittest.main()
